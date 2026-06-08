import json
from datetime import date, datetime, time, timezone

import requests
from flask import current_app

from app.extensions import db
from app.models import (
    ActionItem,
    DailyBriefing,
    DocumentAnalysis,
    Insight,
    RiskFlag,
    SourceFile,
    utcnow,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _compact(value, limit=1200):
    if not value:
        return ""

    value = str(value).strip()

    if len(value) <= limit:
        return value

    return value[: limit - 3].rstrip() + "..."


def _date_bounds(target_date):
    start = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)
    return start, end


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _estimate_tokens(text):
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _extract_openai_text(data):
    if not data:
        return ""

    output_text = data.get("output_text")
    if output_text:
        return output_text

    parts = []

    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if text:
                parts.append(text)

    return "\n\n".join(parts).strip()


def _build_evidence_pack(target_date):
    start, end = _date_bounds(target_date)

    documents = (
        SourceFile.query
        .filter(SourceFile.created_at >= start, SourceFile.created_at <= end)
        .order_by(SourceFile.created_at.asc())
        .limit(60)
        .all()
    )

    processed_documents = (
        SourceFile.query
        .filter(SourceFile.processed_at >= start, SourceFile.processed_at <= end)
        .order_by(SourceFile.processed_at.asc())
        .limit(60)
        .all()
    )

    analyses = (
        DocumentAnalysis.query
        .filter(DocumentAnalysis.created_at >= start, DocumentAnalysis.created_at <= end)
        .order_by(DocumentAnalysis.created_at.asc())
        .limit(40)
        .all()
    )

    insights = (
        Insight.query
        .filter(Insight.created_at >= start, Insight.created_at <= end)
        .order_by(Insight.created_at.asc())
        .limit(40)
        .all()
    )

    risks = (
        RiskFlag.query
        .filter(RiskFlag.created_at >= start, RiskFlag.created_at <= end)
        .order_by(RiskFlag.created_at.asc())
        .limit(40)
        .all()
    )

    actions = (
        ActionItem.query
        .filter(ActionItem.created_at >= start, ActionItem.created_at <= end)
        .order_by(ActionItem.created_at.asc())
        .limit(40)
        .all()
    )

    source_file_ids = sorted(
        {
            *[doc.id for doc in documents],
            *[doc.id for doc in processed_documents],
            *[analysis.source_file_id for analysis in analyses if analysis.source_file_id],
            *[risk.source_file_id for risk in risks if risk.source_file_id],
            *[action.source_file_id for action in actions if action.source_file_id],
        }
    )

    analysis_items = []
    for analysis in analyses:
        doc = SourceFile.query.get(analysis.source_file_id)
        analysis_items.append(
            {
                "source_file_id": analysis.source_file_id,
                "filename": doc.original_filename if doc else f"Document {analysis.source_file_id}",
                "business_area": doc.business_area if doc else None,
                "category": doc.document_category if doc else None,
                "summary": _compact(analysis.summary, 1000),
                "detailed_summary": _compact(analysis.detailed_summary, 1200),
                "key_points": (analysis.key_points_json or [])[:8],
                "risks": (analysis.risks_json or [])[:6],
                "opportunities": (analysis.opportunities_json or [])[:6],
                "actions": (analysis.actions_json or [])[:6],
                "due_diligence": analysis.due_diligence_json or {},
                "buyer_questions": (analysis.buyer_questions_json or [])[:8],
                "evidence_strength": analysis.evidence_strength,
                "confidence_score": analysis.confidence_score,
            }
        )

    evidence_pack = {
        "briefing_date": target_date.isoformat(),
        "counts": {
            "documents_uploaded_today": len(documents),
            "documents_processed_today": len(processed_documents),
            "analyses_created_today": len(analyses),
            "insights_created_today": len(insights),
            "risks_created_today": len(risks),
            "actions_created_today": len(actions),
        },
        "documents_uploaded_today": [
            {
                "id": doc.id,
                "filename": doc.original_filename,
                "file_ext": doc.file_ext,
                "source_type": doc.source_type,
                "processing_status": doc.processing_status,
                "business_area": doc.business_area,
                "category": doc.document_category,
                "sensitivity": doc.sensitivity_level,
            }
            for doc in documents
        ],
        "documents_processed_today": [
            {
                "id": doc.id,
                "filename": doc.original_filename,
                "processing_status": doc.processing_status,
                "business_area": doc.business_area,
                "category": doc.document_category,
            }
            for doc in processed_documents
        ],
        "document_analyses_created_today": analysis_items,
        "insights_created_today": [
            {
                "title": item.title,
                "insight_type": item.insight_type,
                "business_area": item.business_area,
                "severity": item.severity,
                "summary": _compact(item.summary, 900),
                "why_it_matters": _compact(item.why_it_matters, 700),
                "buyer_relevance": _compact(item.buyer_relevance, 700),
                "suggested_action": _compact(item.suggested_action, 600),
            }
            for item in insights
        ],
        "risks_created_today": [
            {
                "title": item.title,
                "risk_type": item.risk_type,
                "business_area": item.business_area,
                "severity": item.severity,
                "buyer_relevance": _compact(item.buyer_relevance, 700),
                "summary": _compact(item.summary, 900),
                "mitigation": _compact(item.mitigation, 700),
                "owner": item.owner,
            }
            for item in risks
        ],
        "actions_created_today": [
            {
                "title": item.title,
                "description": _compact(item.description, 800),
                "owner": item.owner,
                "priority": item.priority,
                "status": item.status,
                "business_area": item.business_area,
                "source_snippet": _compact(item.source_snippet, 500),
            }
            for item in actions
        ],
        "source_file_ids": source_file_ids,
    }

    return evidence_pack, source_file_ids


def _call_openai_for_briefing(prompt):
    if not current_app.config.get("OPENAI_ENABLED"):
        raise RuntimeError("OpenAI is disabled. Set OPENAI_ENABLED=true to use end-of-day GPT briefings.")

    api_key = current_app.config.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = current_app.config.get("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": prompt,
        "temperature": 0.2,
    }

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers=headers,
        json=payload,
        timeout=900,
    )
    response.raise_for_status()

    data = response.json()
    text = _extract_openai_text(data)

    if not text:
        raise RuntimeError("OpenAI returned no briefing text.")

    usage = data.get("usage", {}) or {}

    return text, model, usage


def _build_prompt(target_date, evidence_pack):
    evidence_json = json.dumps(evidence_pack, ensure_ascii=False, default=_json_default, indent=2)

    return f"""
You are writing an end-of-day executive briefing for a senior leader preparing a business for a PE exit process.

Write a polished narrative briefing in clear paragraphs. Do not produce JSON. Do not use long bullet lists. Use short section headings and concise paragraphs.

Use only the supplied SignalDesk evidence. Do not invent facts. If evidence is thin, say that the day appears light on new extracted intelligence.

The briefing should cover:
1. Executive overview
2. Operational and workforce themes
3. Risks and concerns
4. Opportunities and positive signals
5. Due diligence / PE exit relevance
6. Recommended next-day focus

Tone:
- Direct, professional and evidence-led.
- Suitable for a CEO, executive team member, adviser or PE-readiness file.
- Focus on what changed today, what matters, what needs attention tomorrow, and what could matter to a buyer or investor.

Briefing date: {target_date.isoformat()}

SIGNALDESK EVIDENCE PACK:
{evidence_json}
""".strip()


def queue_placeholder(target_date=None):
    briefing_date = target_date or date.today()
    briefing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if not briefing:
        briefing = DailyBriefing(
            briefing_date=briefing_date,
            title=f"End of Day Briefing - {briefing_date.isoformat()}",
            executive_summary="End-of-day GPT briefing queued. The worker will generate it in the background.",
            highlights_json=[],
            risks_json=[],
            opportunities_json=[],
            actions_json=[],
            exit_readiness_json={"briefing_type": "end_of_day"},
            source_file_ids_json=[],
            provider="end_of_day_queued",
            model_name="worker",
        )
        db.session.add(briefing)
    else:
        briefing.title = f"End of Day Briefing - {briefing_date.isoformat()}"
        briefing.executive_summary = "End-of-day GPT briefing queued. The worker will generate it in the background."
        briefing.provider = "end_of_day_queued"
        briefing.model_name = "worker"
        briefing.exit_readiness_json = {
            **(briefing.exit_readiness_json or {}),
            "briefing_type": "end_of_day",
        }
        briefing.updated_at = utcnow()

    db.session.commit()
    return briefing


def generate_end_of_day_briefing(target_date=None):
    briefing_date = target_date or date.today()

    briefing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if not briefing:
        briefing = DailyBriefing(
            briefing_date=briefing_date,
            title=f"End of Day Briefing - {briefing_date.isoformat()}",
            executive_summary="End-of-day GPT briefing is running.",
            highlights_json=[],
            risks_json=[],
            opportunities_json=[],
            actions_json=[],
            exit_readiness_json={"briefing_type": "end_of_day"},
            source_file_ids_json=[],
            provider="end_of_day_running",
            model_name="openai",
        )
        db.session.add(briefing)
    else:
        briefing.title = f"End of Day Briefing - {briefing_date.isoformat()}"
        briefing.executive_summary = "End-of-day GPT briefing is running."
        briefing.provider = "end_of_day_running"
        briefing.model_name = "openai"
        briefing.exit_readiness_json = {
            **(briefing.exit_readiness_json or {}),
            "briefing_type": "end_of_day",
        }
        briefing.updated_at = utcnow()

    db.session.commit()

    evidence_pack, source_file_ids = _build_evidence_pack(briefing_date)
    prompt = _build_prompt(briefing_date, evidence_pack)
    input_token_estimate = _estimate_tokens(prompt)

    try:
        briefing_text, model_name, usage = _call_openai_for_briefing(prompt)
        provider = "openai"
        error = None
    except Exception as exc:
        briefing_text = (
            "End-of-day GPT briefing could not be generated. "
            f"Reason: {exc}\n\n"
            "The evidence pack was built successfully, but the OpenAI call failed. "
            "Check OPENAI_ENABLED, OPENAI_API_KEY, network access and model settings."
        )
        model_name = current_app.config.get("OPENAI_DEFAULT_MODEL", "openai")
        usage = {}
        provider = "end_of_day_failed"
        error = str(exc)

    output_token_estimate = _estimate_tokens(briefing_text)

    briefing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if not briefing:
        briefing = DailyBriefing(briefing_date=briefing_date)
        db.session.add(briefing)

    briefing.title = f"End of Day Briefing - {briefing_date.isoformat()}"
    briefing.executive_summary = briefing_text
    briefing.highlights_json = [
        {
            "title": "End-of-day GPT narrative",
            "summary": "Written narrative briefing generated from the day’s SignalDesk evidence pack.",
        }
    ]
    briefing.risks_json = []
    briefing.opportunities_json = []
    briefing.actions_json = []
    briefing.exit_readiness_json = {
        "briefing_type": "end_of_day",
        "evidence_counts": evidence_pack.get("counts", {}),
        "input_token_estimate": input_token_estimate,
        "output_token_estimate": output_token_estimate,
        "openai_usage": usage,
        "error": error,
    }
    briefing.source_file_ids_json = source_file_ids
    briefing.provider = provider
    briefing.model_name = model_name
    briefing.updated_at = utcnow()

    db.session.commit()

    return briefing
