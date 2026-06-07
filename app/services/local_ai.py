import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from flask import current_app

from app.extensions import db
from app.models import (
    AIProcessingRun,
    DocumentAnalysis,
    DocumentChunk,
    SourceFile,
    utcnow,
)


TRIAGE_PROMPT_VERSION = "triage_v1"
STRUCTURED_EXTRACTION_PROMPT_VERSION = "structured_extraction_v1"
SUMMARY_REVIEW_PROMPT_VERSION = "summary_review_v1"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _compact_text(text: str, max_chars: int = 18000) -> str:
    if not text:
        return ""

    text = text.replace("\x00", "")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text[:max_chars].strip()


def _json_loads_safe(raw: str) -> dict[str, Any]:
    if not raw:
        return {}

    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            pass

    return {
        "parse_error": True,
        "raw_response": raw[:6000],
    }


def _ollama_generate(model: str, prompt: str, expect_json: bool = True) -> tuple[str, int, int]:
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    }

    if expect_json:
        payload["format"] = "json"

    response = requests.post(url, json=payload, timeout=600)
    response.raise_for_status()

    data = response.json()
    output = data.get("response", "") or ""

    input_tokens = data.get("prompt_eval_count") or _estimate_tokens(prompt)
    output_tokens = data.get("eval_count") or _estimate_tokens(output)

    return output, input_tokens, output_tokens


def _create_run(
    source_file_id: int,
    run_type: str,
    provider: str,
    model_name: str,
    prompt_version: str,
) -> AIProcessingRun:
    run = AIProcessingRun(
        source_file_id=source_file_id,
        run_type=run_type,
        provider=provider,
        model_name=model_name,
        prompt_version=prompt_version,
        status="running",
        started_at=utcnow(),
        estimated_cost=0,
    )
    db.session.add(run)
    db.session.flush()
    return run


def _finish_run(
    run: AIProcessingRun,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_message: str | None = None,
):
    run.status = status
    run.input_token_estimate = input_tokens
    run.output_token_estimate = output_tokens
    run.error_message = error_message
    run.finished_at = utcnow()
    run.estimated_cost = Decimal("0.0000")
    db.session.add(run)


def _get_document_text(source_file: SourceFile) -> str:
    if source_file.document_text and source_file.document_text.extracted_text_path:
        path = Path(source_file.document_text.extracted_text_path)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")

    chunks = (
        DocumentChunk.query
        .filter_by(source_file_id=source_file.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )

    if chunks:
        return "\n\n".join(chunk.chunk_text for chunk in chunks)

    if source_file.document_text and source_file.document_text.text_preview:
        return source_file.document_text.text_preview

    return ""


def _build_context(source_file: SourceFile, max_chars: int = 18000) -> str:
    text = _get_document_text(source_file)
    text = _compact_text(text, max_chars=max_chars)

    metadata = [
        f"Filename: {source_file.original_filename}",
        f"File extension: {source_file.file_ext or ''}",
        f"Existing business area: {source_file.business_area or 'Unknown'}",
        f"Document category: {source_file.document_category or 'Unknown'}",
    ]

    if source_file.email_message:
        metadata.extend(
            [
                f"Email subject: {source_file.email_message.subject or ''}",
                f"Email sender: {source_file.email_message.sender_name or ''} <{source_file.email_message.sender_email or ''}>",
                f"Email sent at: {source_file.email_message.sent_at or ''}",
            ]
        )

    return "\n".join(metadata) + "\n\n--- EXTRACTED TEXT ---\n" + text


def run_local_triage(source_file: SourceFile) -> dict[str, Any]:
    model = current_app.config.get("LOCAL_TRIAGE_MODEL", "qwen2.5-coder:3b")
    context = _build_context(source_file, max_chars=10000)

    prompt = f"""
You are SignalDesk's local triage model.

Analyse the document context and return ONLY valid JSON.

Classify the document from the perspective of:
- executive business monitoring
- PE exit readiness
- due diligence
- risk and governance
- recruitment/workforce where relevant

Return this exact JSON structure:
{{
  "document_category": "",
  "business_areas": [],
  "primary_business_area": "",
  "urgency": "Low|Medium|High",
  "sensitivity": "Low|Medium|High",
  "exit_relevance": "None|Low|Medium|High",
  "cloud_review_recommended": false,
  "reason": "",
  "suggested_next_step": ""
}}

Business areas can include:
Executive / Board, Finance, Commercial, Operations, Quality & Compliance,
HR / Workforce, Recruitment, IT / Systems, Legal / Corporate,
Property / Estates, Marketing / Brand, PE Exit / Due Diligence,
Risk & Governance, Strategy, M&A / Integration.

DOCUMENT CONTEXT:
{context}
""".strip()

    run = _create_run(
        source_file.id,
        "local_triage",
        "ollama",
        model,
        TRIAGE_PROMPT_VERSION,
    )

    try:
        output, input_tokens, output_tokens = _ollama_generate(model, prompt, expect_json=True)
        parsed = _json_loads_safe(output)

        _finish_run(run, "success", input_tokens, output_tokens)
        db.session.commit()
        return parsed

    except Exception as exc:
        _finish_run(run, "failed", error_message=str(exc))
        db.session.commit()
        raise


def run_structured_extraction(source_file: SourceFile) -> dict[str, Any]:
    model = current_app.config.get("LOCAL_EXTRACTION_MODEL", "qwen2.5-coder:7b")
    context = _build_context(source_file, max_chars=16000)

    prompt = f"""
You are SignalDesk's structured extraction model.

Extract business-useful structured information from the document.

Return ONLY valid JSON using this exact structure:
{{
  "actions": [
    {{
      "title": "",
      "description": "",
      "owner": "",
      "due_date": "",
      "priority": "Low|Medium|High|Unknown",
      "source_snippet": ""
    }}
  ],
  "decisions": [
    {{
      "decision": "",
      "decision_owner": "",
      "date_or_context": "",
      "source_snippet": ""
    }}
  ],
  "entities": [
    {{
      "name": "",
      "entity_type": "Person|Company|Service|Department|Location|Project|Buyer|Investor|Supplier|Regulator|Contract|Other",
      "context": ""
    }}
  ],
  "important_dates": [],
  "financial_values": [],
  "open_questions": [],
  "missing_information": []
}}

Rules:
- Do not invent owners, dates, values or decisions.
- Use empty strings or empty lists when not present.
- Keep snippets short and evidence-based.
- Focus on executive, operational, workforce, financial, compliance and PE exit relevance.

DOCUMENT CONTEXT:
{context}
""".strip()

    run = _create_run(
        source_file.id,
        "local_structured_extraction",
        "ollama",
        model,
        STRUCTURED_EXTRACTION_PROMPT_VERSION,
    )

    try:
        output, input_tokens, output_tokens = _ollama_generate(model, prompt, expect_json=True)
        parsed = _json_loads_safe(output)

        _finish_run(run, "success", input_tokens, output_tokens)
        db.session.commit()
        return parsed

    except Exception as exc:
        _finish_run(run, "failed", error_message=str(exc))
        db.session.commit()
        raise


def run_summary_review(source_file: SourceFile) -> dict[str, Any]:
    model = current_app.config.get("LOCAL_SUMMARY_MODEL", "llama3.1:8b")
    context = _build_context(source_file, max_chars=18000)

    prompt = f"""
You are SignalDesk's executive document review model.

Review the document from the perspective of:
- executive leadership
- business performance
- risk and governance
- PE exit readiness
- due diligence readiness
- buyer challenge areas

Return ONLY valid JSON using this exact structure:
{{
  "summary": "",
  "detailed_summary": "",
  "key_points": [],
  "risks": [
    {{
      "title": "",
      "severity": "Green|Amber|Red",
      "confidence": "Low|Medium|High",
      "business_area": "",
      "why_it_matters": "",
      "buyer_relevance": "",
      "source_snippet": ""
    }}
  ],
  "opportunities": [
    {{
      "title": "",
      "category": "",
      "why_it_matters": "",
      "source_snippet": ""
    }}
  ],
  "due_diligence": {{
    "is_relevant": false,
    "category": "",
    "buyer_interest_level": "None|Low|Medium|High",
    "evidence_strength": "Low|Medium|High",
    "evidence_gaps": [],
    "likely_buyer_questions": []
  }},
  "email_response": {{
    "response_needed": false,
    "urgency": "Low|Medium|High",
    "suggested_angle": "",
    "draft_response": ""
  }},
  "recommended_follow_up": []
}}

Rules:
- Be cautious. Say "possible" or "may" unless the document provides strong evidence.
- Do not invent facts.
- Every risk must include a short source snippet.
- If this is routine with no material issue, say so.
- Focus on what a Head of Recruitment and Executive Team member would need to know.

DOCUMENT CONTEXT:
{context}
""".strip()

    run = _create_run(
        source_file.id,
        "local_summary_review",
        "ollama",
        model,
        SUMMARY_REVIEW_PROMPT_VERSION,
    )

    try:
        output, input_tokens, output_tokens = _ollama_generate(model, prompt, expect_json=True)
        parsed = _json_loads_safe(output)

        _finish_run(run, "success", input_tokens, output_tokens)
        db.session.commit()
        return parsed

    except Exception as exc:
        _finish_run(run, "failed", error_message=str(exc))
        db.session.commit()
        raise


def run_full_local_ai_review(source_file_id: int) -> DocumentAnalysis:
    source_file = SourceFile.query.get(source_file_id)

    if not source_file:
        raise ValueError(f"SourceFile not found: {source_file_id}")

    if not source_file.document_text or not source_file.document_text.text_preview:
        raise ValueError("Document must be processed/extracted before running local AI review.")

    source_file.processing_status = "local_ai_reviewing"
    db.session.commit()

    triage = run_local_triage(source_file)

    primary_area = triage.get("primary_business_area")
    document_category = triage.get("document_category")
    sensitivity = triage.get("sensitivity")

    if primary_area:
        source_file.business_area = primary_area

    if document_category:
        source_file.document_category = document_category

    if sensitivity:
        source_file.sensitivity_level = sensitivity

    db.session.add(source_file)
    db.session.commit()

    structured = run_structured_extraction(source_file)
    review = run_summary_review(source_file)

    analysis = DocumentAnalysis.query.filter_by(source_file_id=source_file.id).first()

    if not analysis:
        analysis = DocumentAnalysis(source_file_id=source_file.id)
        db.session.add(analysis)

    analysis.provider = "ollama"
    analysis.model_name = (
        f"{current_app.config.get('LOCAL_TRIAGE_MODEL')} | "
        f"{current_app.config.get('LOCAL_EXTRACTION_MODEL')} | "
        f"{current_app.config.get('LOCAL_SUMMARY_MODEL')}"
    )

    analysis.summary = review.get("summary")
    analysis.detailed_summary = review.get("detailed_summary")

    analysis.key_points_json = review.get("key_points", [])
    analysis.decisions_json = structured.get("decisions", [])
    analysis.actions_json = structured.get("actions", [])
    analysis.risks_json = review.get("risks", [])
    analysis.opportunities_json = review.get("opportunities", [])
    analysis.entities_json = structured.get("entities", [])

    due_diligence = review.get("due_diligence", {})
    due_diligence["triage"] = triage
    analysis.due_diligence_json = due_diligence

    analysis.buyer_questions_json = due_diligence.get("likely_buyer_questions", [])

    analysis.evidence_strength = due_diligence.get("evidence_strength")
    analysis.confidence_score = None

    source_file.processing_status = "local_ai_complete"
    source_file.processing_error = None
    source_file.processed_at = utcnow()

    db.session.add(analysis)
    db.session.add(source_file)
    db.session.commit()

    return analysis
