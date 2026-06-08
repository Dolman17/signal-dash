from collections import defaultdict
from datetime import datetime, timezone

from app.models import ActionItem, DocumentAnalysis, Insight, RiskFlag, SourceFile


DUE_DILIGENCE_CATEGORIES = [
    {
        "slug": "people-workforce",
        "name": "People & Workforce",
        "keywords": ["people", "workforce", "employee", "hr", "staff", "headcount", "absence", "turnover", "training"],
        "expected_evidence": ["Organisation chart", "Workforce plan", "Turnover/retention data", "Training/compliance evidence"],
    },
    {
        "slug": "recruitment-retention",
        "name": "Recruitment & Retention",
        "keywords": ["recruitment", "retention", "vacancy", "candidate", "ats", "hiring", "agency", "onboarding"],
        "expected_evidence": ["Vacancy trend", "Recruitment pipeline", "Time-to-hire data", "Retention actions"],
    },
    {
        "slug": "contracts-commercial",
        "name": "Contracts & Commercial",
        "keywords": ["contract", "commercial", "client", "pricing", "fee", "rate", "commission", "revenue", "tender"],
        "expected_evidence": ["Contract register", "Pricing/rate evidence", "Key client terms", "Commercial risk notes"],
    },
    {
        "slug": "operations-service-delivery",
        "name": "Operations & Service Delivery",
        "keywords": ["operations", "service", "delivery", "rota", "branch", "care", "quality", "capacity", "performance"],
        "expected_evidence": ["Operational KPIs", "Service performance data", "Capacity/rota evidence", "Quality actions"],
    },
    {
        "slug": "finance-cost-pressure",
        "name": "Finance & Cost Pressure",
        "keywords": ["finance", "cost", "ebitda", "margin", "pay", "salary", "budget", "forecast", "invoice"],
        "expected_evidence": ["Budget/forecast evidence", "Cost pressure analysis", "Pay-rate evidence", "Margin/EBITDA commentary"],
    },
    {
        "slug": "compliance-regulation",
        "name": "Compliance & Regulation",
        "keywords": ["compliance", "regulation", "regulatory", "cqc", "audit", "policy", "safeguarding", "incident", "gdpr"],
        "expected_evidence": ["Policy register", "Audit evidence", "Regulatory correspondence", "Incident/risk records"],
    },
    {
        "slug": "technology-systems",
        "name": "Technology & Systems",
        "keywords": ["technology", "system", "it", "software", "security", "data", "cyber", "backup", "integration"],
        "expected_evidence": ["System register", "Cyber/security evidence", "Backup/DR evidence", "Data protection evidence"],
    },
    {
        "slug": "legal-risk-governance",
        "name": "Legal / Risk / Governance",
        "keywords": ["legal", "risk", "governance", "board", "minutes", "litigation", "claim", "insurance", "policy"],
        "expected_evidence": ["Risk register", "Board/management minutes", "Insurance/legal records", "Governance actions"],
    },
    {
        "slug": "growth-opportunities",
        "name": "Growth Opportunities",
        "keywords": ["growth", "opportunity", "pipeline", "expansion", "new service", "market", "buyer", "cross-sell"],
        "expected_evidence": ["Growth pipeline", "Market/opportunity notes", "New service plans", "Buyer upside evidence"],
    },
    {
        "slug": "management-capability",
        "name": "Management Capability",
        "keywords": ["management", "leadership", "director", "ceo", "exec", "manager", "accountability", "owner"],
        "expected_evidence": ["Leadership structure", "Management reporting", "Accountability/actions", "Decision logs"],
    },
]

CATEGORY_BY_SLUG = {category["slug"]: category for category in DUE_DILIGENCE_CATEGORIES}

SEVERITY_WEIGHT = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

EVIDENCE_STRENGTH_WEIGHT = {
    "strong": 3,
    "good": 3,
    "adequate": 2,
    "moderate": 2,
    "weak": 1,
    "limited": 1,
}


def _normalise_text(*values):
    return " ".join(str(value or "").lower() for value in values)


def _contains_any(text, keywords):
    return any(keyword in text for keyword in keywords)


def _analysis_due_diligence_text(analysis):
    due_diligence = analysis.due_diligence_json or {}
    buyer_questions = analysis.buyer_questions_json or []
    return _normalise_text(
        analysis.summary,
        analysis.detailed_summary,
        analysis.key_points_json,
        analysis.decisions_json,
        analysis.actions_json,
        analysis.risks_json,
        analysis.opportunities_json,
        analysis.entities_json,
        due_diligence,
        buyer_questions,
        analysis.evidence_strength,
    )


def _document_text(document):
    return _normalise_text(
        document.original_filename,
        document.file_ext,
        document.mime_type,
        document.source_type,
        document.processing_status,
        document.document_category,
        document.business_area,
        document.sensitivity_level,
        document.processing_error,
    )


def _risk_text(risk):
    return _normalise_text(
        risk.title,
        risk.summary,
        risk.risk_type,
        risk.business_area,
        risk.severity,
        risk.buyer_relevance,
        risk.mitigation,
        risk.owner,
        risk.status,
    )


def _action_text(action):
    return _normalise_text(
        action.title,
        action.description,
        action.owner,
        action.priority,
        action.status,
        action.business_area,
        action.source_snippet,
    )


def _insight_text(insight):
    return _normalise_text(
        insight.title,
        insight.summary,
        insight.insight_type,
        insight.business_area,
        insight.severity,
        insight.why_it_matters,
        insight.buyer_relevance,
        insight.suggested_action,
    )


def _categories_for_text(text):
    matched = []
    for category in DUE_DILIGENCE_CATEGORIES:
        if _contains_any(text, category["keywords"]):
            matched.append(category["slug"])

    return matched or ["legal-risk-governance"]


def _blank_category_summary(category):
    return {
        "slug": category["slug"],
        "name": category["name"],
        "expected_evidence": category["expected_evidence"],
        "documents": [],
        "analyses": [],
        "risks": [],
        "actions": [],
        "insights": [],
        "counts": {
            "documents": 0,
            "analyses": 0,
            "risks": 0,
            "actions": 0,
            "insights": 0,
            "open_actions": 0,
            "high_risks": 0,
        },
        "score": 0,
        "status": "Insufficient Evidence",
        "reason": "No material evidence has been linked to this category yet.",
        "missing_evidence": list(category["expected_evidence"]),
        "buyer_questions": [],
    }


def _unique_append(items, item, key="id", limit=20):
    item_key = item.get(key)
    if item_key is None:
        item_key = item.get("title") or item.get("name")

    if all((existing.get(key) if existing.get(key) is not None else existing.get("title") or existing.get("name")) != item_key for existing in items):
        items.append(item)

    if len(items) > limit:
        del items[limit:]


def _score_category(summary):
    counts = summary["counts"]
    evidence_points = min(35, counts["documents"] * 4 + counts["analyses"] * 5 + counts["insights"] * 3)
    action_points = min(15, counts["actions"] * 2)

    risk_penalty = min(30, counts["high_risks"] * 8)
    open_action_penalty = min(15, counts["open_actions"] * 2)

    score = max(0, min(100, 35 + evidence_points + action_points - risk_penalty - open_action_penalty))

    if counts["documents"] == 0 and counts["analyses"] == 0:
        status = "Insufficient Evidence"
        reason = "No source evidence has been identified for this due diligence category."
    elif counts["high_risks"] >= 3:
        status = "High Risk"
        reason = "Multiple high-severity risks are linked to this category and should be addressed before buyer review."
    elif score >= 75:
        status = "Strong"
        reason = "Evidence is reasonably developed and linked intelligence suggests this area is supportable."
    elif score >= 55:
        status = "Adequate"
        reason = "There is useful evidence, but open actions or further documentation would strengthen buyer confidence."
    else:
        status = "Weak"
        reason = "Evidence exists but appears thin, incomplete, or risk-weighted."

    summary["score"] = score
    summary["status"] = status
    summary["reason"] = reason

    present_terms = _normalise_text(summary["documents"], summary["analyses"], summary["risks"], summary["actions"], summary["insights"])
    missing = []
    for expected in summary["expected_evidence"]:
        words = [word.lower() for word in expected.replace("/", " ").split() if len(word) > 3]
        if not any(word in present_terms for word in words):
            missing.append(expected)
    summary["missing_evidence"] = missing

    return summary


def build_due_diligence_library():
    summaries = {category["slug"]: _blank_category_summary(category) for category in DUE_DILIGENCE_CATEGORIES}

    documents = SourceFile.query.order_by(SourceFile.created_at.desc()).limit(500).all()
    analyses = DocumentAnalysis.query.order_by(DocumentAnalysis.created_at.desc()).limit(500).all()
    risks = RiskFlag.query.order_by(RiskFlag.created_at.desc()).limit(500).all()
    actions = ActionItem.query.order_by(ActionItem.created_at.desc()).limit(500).all()
    insights = Insight.query.order_by(Insight.created_at.desc()).limit(500).all()

    for document in documents:
        item = {
            "id": document.id,
            "title": document.original_filename,
            "status": document.processing_status,
            "business_area": document.business_area,
            "category": document.document_category,
            "created_at": document.created_at,
        }
        for slug in _categories_for_text(_document_text(document)):
            _unique_append(summaries[slug]["documents"], item, limit=30)

    for analysis in analyses:
        document = SourceFile.query.get(analysis.source_file_id) if analysis.source_file_id else None
        item = {
            "id": analysis.id,
            "source_file_id": analysis.source_file_id,
            "title": document.original_filename if document else f"Analysis {analysis.id}",
            "summary": analysis.summary,
            "evidence_strength": analysis.evidence_strength,
            "confidence_score": analysis.confidence_score,
            "created_at": analysis.created_at,
            "buyer_questions": analysis.buyer_questions_json or [],
        }
        for slug in _categories_for_text(_analysis_due_diligence_text(analysis) + " " + _document_text(document) if document else _analysis_due_diligence_text(analysis)):
            _unique_append(summaries[slug]["analyses"], item, limit=30)
            for question in (analysis.buyer_questions_json or [])[:5]:
                _unique_append(
                    summaries[slug]["buyer_questions"],
                    {
                        "title": str(question)[:500],
                        "source_file_id": analysis.source_file_id,
                        "category": summaries[slug]["name"],
                        "recommended_angle": "Use the linked evidence and document analysis to answer directly; flag gaps if the evidence is incomplete.",
                    },
                    key="title",
                    limit=12,
                )

    for risk in risks:
        item = {
            "id": risk.id,
            "source_file_id": risk.source_file_id,
            "title": risk.title,
            "summary": risk.summary,
            "severity": risk.severity,
            "status": risk.status,
            "business_area": risk.business_area,
            "buyer_relevance": risk.buyer_relevance,
            "created_at": risk.created_at,
        }
        for slug in _categories_for_text(_risk_text(risk)):
            _unique_append(summaries[slug]["risks"], item, limit=30)

    for action in actions:
        item = {
            "id": action.id,
            "source_file_id": action.source_file_id,
            "title": action.title,
            "description": action.description,
            "priority": action.priority,
            "status": action.status,
            "owner": action.owner,
            "business_area": action.business_area,
            "created_at": action.created_at,
        }
        for slug in _categories_for_text(_action_text(action)):
            _unique_append(summaries[slug]["actions"], item, limit=30)

    for insight in insights:
        item = {
            "id": insight.id,
            "title": insight.title,
            "summary": insight.summary,
            "severity": insight.severity,
            "insight_type": insight.insight_type,
            "business_area": insight.business_area,
            "buyer_relevance": insight.buyer_relevance,
            "created_at": insight.created_at,
        }
        for slug in _categories_for_text(_insight_text(insight)):
            _unique_append(summaries[slug]["insights"], item, limit=30)

    for summary in summaries.values():
        summary["counts"]["documents"] = len(summary["documents"])
        summary["counts"]["analyses"] = len(summary["analyses"])
        summary["counts"]["risks"] = len(summary["risks"])
        summary["counts"]["actions"] = len(summary["actions"])
        summary["counts"]["insights"] = len(summary["insights"])
        summary["counts"]["open_actions"] = len([a for a in summary["actions"] if str(a.get("status") or "").lower() not in {"done", "closed", "complete", "completed"}])
        summary["counts"]["high_risks"] = len([r for r in summary["risks"] if SEVERITY_WEIGHT.get(str(r.get("severity") or "").lower(), 0) >= 3])
        _score_category(summary)

    categories = list(summaries.values())
    categories.sort(key=lambda item: (item["status"] == "Insufficient Evidence", -item["score"], item["name"]))

    totals = {
        "categories": len(categories),
        "strong": len([c for c in categories if c["status"] == "Strong"]),
        "adequate": len([c for c in categories if c["status"] == "Adequate"]),
        "weak": len([c for c in categories if c["status"] == "Weak"]),
        "high_risk": len([c for c in categories if c["status"] == "High Risk"]),
        "insufficient": len([c for c in categories if c["status"] == "Insufficient Evidence"]),
        "overall_score": int(sum(c["score"] for c in categories) / max(1, len(categories))),
    }

    return {
        "categories": categories,
        "category_map": summaries,
        "totals": totals,
        "generated_at": datetime.now(timezone.utc),
    }


def build_evidence_gaps(library=None):
    library = library or build_due_diligence_library()
    gaps = []

    for category in library["categories"]:
        if category["status"] == "Insufficient Evidence":
            priority = "High"
        elif category["status"] in {"Weak", "High Risk"}:
            priority = "Medium"
        else:
            priority = "Low"

        for missing in category["missing_evidence"]:
            gaps.append(
                {
                    "title": missing,
                    "category_slug": category["slug"],
                    "category": category["name"],
                    "priority": priority,
                    "status": "Open",
                    "why_it_matters": f"Buyers may ask for clear evidence covering {missing.lower()} within {category['name']}.",
                    "suggested_owner": "Executive / functional lead",
                    "suggested_action": f"Upload or link current evidence for {missing.lower()} and rerun local AI review.",
                    "linked_documents": category["documents"][:5],
                }
            )

    gaps.sort(key=lambda item: ({"High": 0, "Medium": 1, "Low": 2}.get(item["priority"], 3), item["category"], item["title"]))
    return gaps


def build_buyer_questions(library=None):
    library = library or build_due_diligence_library()
    questions = []

    default_questions = {
        "People & Workforce": [
            "What is the current workforce risk profile and how is management addressing retention?",
            "Where is the evidence for training, compliance and management oversight?",
        ],
        "Recruitment & Retention": [
            "What is the vacancy trend and how resilient is the recruitment pipeline?",
            "How dependent is the business on agency or hard-to-fill roles?",
        ],
        "Contracts & Commercial": [
            "Which contracts, pricing terms or commercial dependencies could affect maintainable earnings?",
            "Where is the evidence for contract quality and renewal risk?",
        ],
        "Operations & Service Delivery": [
            "What operational issues could affect continuity, quality or scalability?",
            "How strong is management visibility over service delivery?",
        ],
        "Finance & Cost Pressure": [
            "What cost pressures could affect EBITDA quality or margin sustainability?",
            "Where is the evidence for pay, cost and forecast assumptions?",
        ],
        "Compliance & Regulation": [
            "What compliance risks are open and what evidence supports mitigation?",
            "Where is the latest policy, audit or regulatory evidence?",
        ],
        "Technology & Systems": [
            "Which systems are business-critical and how is technology risk controlled?",
            "Where is the evidence for data security, backups and resilience?",
        ],
        "Legal / Risk / Governance": [
            "What governance evidence supports board-level oversight and risk management?",
            "Are there legal, insurance or unresolved risk matters a buyer may challenge?",
        ],
        "Growth Opportunities": [
            "What evidence supports the growth story and buyer upside?",
            "Which growth opportunities are proven versus aspirational?",
        ],
        "Management Capability": [
            "How does the management team demonstrate grip, cadence and accountability?",
            "Where is the evidence of decisions, ownership and follow-through?",
        ],
    }

    for category in library["categories"]:
        for question in category["buyer_questions"]:
            questions.append(
                {
                    "question": question["title"],
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "recommended_angle": question.get("recommended_angle"),
                    "source_file_id": question.get("source_file_id"),
                    "evidence_count": category["counts"]["documents"] + category["counts"]["analyses"],
                    "risk_count": category["counts"]["risks"],
                    "gap_count": len(category["missing_evidence"]),
                }
            )

        for question in default_questions.get(category["name"], []):
            questions.append(
                {
                    "question": question,
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "recommended_angle": "Answer using linked evidence. If evidence is missing, treat this as a diligence gap before buyer engagement.",
                    "source_file_id": None,
                    "evidence_count": category["counts"]["documents"] + category["counts"]["analyses"],
                    "risk_count": category["counts"]["risks"],
                    "gap_count": len(category["missing_evidence"]),
                }
            )

    return questions[:80]


def build_executive_narrative(library=None):
    library = library or build_due_diligence_library()
    totals = library["totals"]
    strong = [c for c in library["categories"] if c["status"] in {"Strong", "Adequate"}]
    weak = [c for c in library["categories"] if c["status"] in {"Weak", "Insufficient Evidence"}]
    high_risk = [c for c in library["categories"] if c["status"] == "High Risk"]

    return {
        "headline": f"Current exit readiness score is {totals['overall_score']}%, with {totals['strong']} strong area(s), {totals['adequate']} adequate area(s), and {totals['high_risk']} high-risk area(s).",
        "what_has_improved": [
            f"{category['name']} has a {category['status'].lower()} evidence position with {category['counts']['documents']} document(s), {category['counts']['insights']} insight(s), and {category['counts']['actions']} action(s)."
            for category in strong[:5]
        ],
        "risk_control": [
            f"{category['name']} needs management attention: {category['reason']}"
            for category in (high_risk + weak)[:6]
        ],
        "buyer_story": [
            "The business is building a source-linked evidence trail rather than relying on unsupported narrative.",
            "Daily extraction, local AI review and end-of-day executive briefings provide a repeatable diligence rhythm.",
            "The next value driver is closing evidence gaps before a buyer or adviser requests them.",
        ],
        "next_focus": [
            f"Strengthen {category['name']} by uploading evidence for: {', '.join(category['missing_evidence'][:3])}."
            for category in weak[:5]
            if category["missing_evidence"]
        ],
    }
