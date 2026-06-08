import json
import re
from datetime import date

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


def _json_loads_safe(raw):
    if not raw:
        return {}

    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {
        "executive_summary": raw[:3000],
        "highlights": [],
        "risks": [],
        "opportunities": [],
        "actions": [],
        "exit_readiness": {},
    }


def _ollama_generate(model, prompt):
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.15,
            "num_ctx": 8192,
        },
    }

    response = requests.post(url, json=payload, timeout=900)
    response.raise_for_status()

    data = response.json()
    return data.get("response", "") or ""


def _compact(value, limit=800):
    if not value:
        return ""

    value = str(value).strip()

    if len(value) <= limit:
        return value

    return value[: limit - 3].rstrip() + "..."


def _build_briefing_context():
    documents = (
        SourceFile.query
        .order_by(SourceFile.created_at.desc())
        .limit(12)
        .all()
    )

    analyses = (
        DocumentAnalysis.query
        .order_by(DocumentAnalysis.created_at.desc())
        .limit(10)
        .all()
    )

    insights = (
        Insight.query
        .filter_by(status="open")
        .order_by(Insight.created_at.desc())
        .limit(10)
        .all()
    )

    risks = (
        RiskFlag.query
        .filter_by(status="open")
        .order_by(RiskFlag.created_at.desc())
        .limit(10)
        .all()
    )

    actions = (
        ActionItem.query
        .filter(ActionItem.status.in_(["open", "in_progress"]))
        .order_by(ActionItem.created_at.desc())
        .limit(10)
        .all()
    )

    source_file_ids = [doc.id for doc in documents]

    lines = []

    lines.append("RECENT DOCUMENTS")
    for doc in documents:
        lines.append(
            f"- ID {doc.id}: {doc.original_filename} | "
            f"Status: {doc.processing_status} | "
            f"Area: {doc.business_area or 'Unknown'} | "
            f"Category: {doc.document_category or 'Unknown'}"
        )

    lines.append("\nRECENT DOCUMENT ANALYSES")
    for analysis in analyses:
        doc = SourceFile.query.get(analysis.source_file_id)
        filename = doc.original_filename if doc else f"Document {analysis.source_file_id}"
        lines.append(f"- {filename}: {_compact(analysis.summary, 1000)}")

        if analysis.risks_json:
            for item in analysis.risks_json[:3]:
                lines.append(
                    f"  Risk: {item.get('title', 'Untitled')} | "
                    f"Severity: {item.get('severity', 'Unknown')} | "
                    f"Why: {_compact(item.get('why_it_matters'), 400)}"
                )

        if analysis.actions_json:
            for item in analysis.actions_json[:3]:
                lines.append(
                    f"  Action: {item.get('title', 'Untitled')} | "
                    f"Owner: {item.get('owner', 'Unknown')} | "
                    f"Priority: {item.get('priority', 'Unknown')}"
                )

    lines.append("\nOPEN INSIGHTS")
    for insight in insights:
        lines.append(
            f"- {insight.title} | Type: {insight.insight_type} | "
            f"Severity: {insight.severity or 'Unknown'} | "
            f"Area: {insight.business_area or 'Unknown'} | "
            f"Summary: {_compact(insight.summary, 600)}"
        )

    lines.append("\nOPEN RISKS")
    for risk in risks:
        lines.append(
            f"- {risk.title} | Severity: {risk.severity or 'Unknown'} | "
            f"Area: {risk.business_area or 'Unknown'} | "
            f"Buyer relevance: {_compact(risk.buyer_relevance, 400)} | "
            f"Summary: {_compact(risk.summary, 600)}"
        )

    lines.append("\nOPEN ACTIONS")
    for action in actions:
        lines.append(
            f"- {action.title} | Owner: {action.owner or 'Unknown'} | "
            f"Priority: {action.priority or 'Unknown'} | "
            f"Area: {action.business_area or 'Unknown'} | "
            f"Description: {_compact(action.description, 500)}"
        )

    return "\n".join(lines), source_file_ids


def _fallback_briefing(briefing_date, source_file_ids):
    open_risks = RiskFlag.query.filter_by(status="open").order_by(RiskFlag.created_at.desc()).limit(5).all()
    open_actions = (
        ActionItem.query
        .filter(ActionItem.status.in_(["open", "in_progress"]))
        .order_by(ActionItem.created_at.desc())
        .limit(5)
        .all()
    )
    open_insights = Insight.query.filter_by(status="open").order_by(Insight.created_at.desc()).limit(5).all()

    return {
        "title": f"Daily Briefing - {briefing_date.isoformat()}",
        "executive_summary": (
            "Daily briefing generated from stored SignalDesk records. "
            "Local AI generation was not available, so this fallback summary uses the latest open risks, actions and insights."
        ),
        "highlights": [
            {"title": item.title, "summary": item.summary or item.why_it_matters or ""}
            for item in open_insights
        ],
        "risks": [
            {
                "title": item.title,
                "severity": item.severity,
                "summary": item.summary,
                "buyer_relevance": item.buyer_relevance,
            }
            for item in open_risks
        ],
        "opportunities": [],
        "actions": [
            {
                "title": item.title,
                "owner": item.owner,
                "priority": item.priority,
                "status": item.status,
            }
            for item in open_actions
        ],
        "exit_readiness": {
            "summary": "Review PE Exit / Due Diligence insights and evidence gaps.",
            "watch_points": [],
        },
        "source_file_ids": source_file_ids,
        "provider": "fallback",
        "model_name": "local-record-summary",
    }


def generate_daily_briefing(target_date=None):
    briefing_date = target_date or date.today()
    context, source_file_ids = _build_briefing_context()

    model = current_app.config.get("LOCAL_SUMMARY_MODEL", "llama3.1:8b")

    prompt = f"""
You are SignalDesk's local executive briefing model.

Create a concise daily executive briefing for a Head of Recruitment and Executive Team member.
The business is preparing for a PE exit process, so include operational, commercial, workforce,
risk, due diligence and buyer-relevance points where supported by evidence.

Return ONLY valid JSON using this exact structure:
{{
  "title": "",
  "executive_summary": "",
  "highlights": [
    {{
      "title": "",
      "summary": "",
      "why_it_matters": "",
      "source_hint": ""
    }}
  ],
  "risks": [
    {{
      "title": "",
      "severity": "Green|Amber|Red",
      "summary": "",
      "buyer_relevance": "",
      "recommended_action": ""
    }}
  ],
  "opportunities": [
    {{
      "title": "",
      "summary": "",
      "why_it_matters": ""
    }}
  ],
  "actions": [
    {{
      "title": "",
      "owner": "",
      "priority": "Low|Medium|High|Unknown",
      "suggested_next_step": ""
    }}
  ],
  "exit_readiness": {{
    "summary": "",
    "watch_points": [],
    "evidence_gaps": [],
    "buyer_questions": []
  }}
}}

Rules:
- Do not invent facts.
- Be cautious and evidence-led.
- Keep the executive summary practical and direct.
- Focus on what needs attention today.
- Prioritise Red/Amber risks, overdue/open actions, PE exit relevance and recurring themes.

SIGNALDESK CONTEXT:
{context}
""".strip()

    provider = "ollama"
    model_name = model

    try:
        raw = _ollama_generate(model, prompt)
        parsed = _json_loads_safe(raw)
    except Exception:
        parsed = _fallback_briefing(briefing_date, source_file_ids)
        provider = "fallback"
        model_name = "local-record-summary"

    briefing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if not briefing:
        briefing = DailyBriefing(briefing_date=briefing_date)
        db.session.add(briefing)

    briefing.title = parsed.get("title") or f"Daily Briefing - {briefing_date.isoformat()}"
    briefing.executive_summary = parsed.get("executive_summary")
    briefing.highlights_json = parsed.get("highlights", [])
    briefing.risks_json = parsed.get("risks", [])
    briefing.opportunities_json = parsed.get("opportunities", [])
    briefing.actions_json = parsed.get("actions", [])
    briefing.exit_readiness_json = parsed.get("exit_readiness", {})
    briefing.source_file_ids_json = source_file_ids
    briefing.provider = provider
    briefing.model_name = model_name
    briefing.updated_at = utcnow()

    db.session.commit()

    return briefing