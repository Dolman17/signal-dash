from datetime import datetime, timezone

from app.models import (
    ActionItem,
    DocumentAnalysis,
    DueDiligenceCategoryNote,
    DueDiligenceEvidence,
    Insight,
    RiskFlag,
    SourceFile,
)


DUE_DILIGENCE_CATEGORIES = [
    {"slug": "people-workforce", "name": "People & Workforce", "keywords": ["people", "workforce", "employee", "hr", "staff", "headcount", "absence", "turnover", "training"], "expected_evidence": ["Organisation chart", "Workforce plan", "Turnover/retention data", "Training/compliance evidence"]},
    {"slug": "recruitment-retention", "name": "Recruitment & Retention", "keywords": ["recruitment", "retention", "vacancy", "candidate", "ats", "hiring", "agency", "onboarding"], "expected_evidence": ["Vacancy trend", "Recruitment pipeline", "Time-to-hire data", "Retention actions"]},
    {"slug": "contracts-commercial", "name": "Contracts & Commercial", "keywords": ["contract", "commercial", "client", "pricing", "fee", "rate", "commission", "revenue", "tender"], "expected_evidence": ["Contract register", "Pricing/rate evidence", "Key client terms", "Commercial risk notes"]},
    {"slug": "operations-service-delivery", "name": "Operations & Service Delivery", "keywords": ["operations", "service", "delivery", "rota", "branch", "care", "quality", "capacity", "performance"], "expected_evidence": ["Operational KPIs", "Service performance data", "Capacity/rota evidence", "Quality actions"]},
    {"slug": "finance-cost-pressure", "name": "Finance & Cost Pressure", "keywords": ["finance", "cost", "ebitda", "margin", "pay", "salary", "budget", "forecast", "invoice"], "expected_evidence": ["Budget/forecast evidence", "Cost pressure analysis", "Pay-rate evidence", "Margin/EBITDA commentary"]},
    {"slug": "compliance-regulation", "name": "Compliance & Regulation", "keywords": ["compliance", "regulation", "regulatory", "cqc", "audit", "policy", "safeguarding", "incident", "gdpr"], "expected_evidence": ["Policy register", "Audit evidence", "Regulatory correspondence", "Incident/risk records"]},
    {"slug": "technology-systems", "name": "Technology & Systems", "keywords": ["technology", "system", "it", "software", "security", "data", "cyber", "backup", "integration"], "expected_evidence": ["System register", "Cyber/security evidence", "Backup/DR evidence", "Data protection evidence"]},
    {"slug": "legal-risk-governance", "name": "Legal / Risk / Governance", "keywords": ["legal", "risk", "governance", "board", "minutes", "litigation", "claim", "insurance", "policy"], "expected_evidence": ["Risk register", "Board/management minutes", "Insurance/legal records", "Governance actions"]},
    {"slug": "growth-opportunities", "name": "Growth Opportunities", "keywords": ["growth", "opportunity", "pipeline", "expansion", "new service", "market", "buyer", "cross-sell"], "expected_evidence": ["Growth pipeline", "Market/opportunity notes", "New service plans", "Buyer upside evidence"]},
    {"slug": "management-capability", "name": "Management Capability", "keywords": ["management", "leadership", "director", "ceo", "exec", "manager", "accountability", "owner"], "expected_evidence": ["Leadership structure", "Management reporting", "Accountability/actions", "Decision logs"]},
]

CATEGORY_BY_SLUG = {category["slug"]: category for category in DUE_DILIGENCE_CATEGORIES}

SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
EVIDENCE_STRENGTH_WEIGHT = {"strong": 3, "good": 3, "adequate": 2, "moderate": 2, "weak": 1, "limited": 1}
MANUAL_STRENGTH_POINTS = {"strong": 12, "adequate": 7, "weak": 2, "not_relevant": -8}
BUYER_RELEVANCE_POINTS = {"high": 7, "medium": 4, "low": 1, "none": -3}


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
    if not document:
        return ""

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
    return _normalise_text(risk.title, risk.summary, risk.risk_type, risk.business_area, risk.severity, risk.buyer_relevance, risk.mitigation, risk.owner, risk.status)


def _action_text(action):
    return _normalise_text(action.title, action.description, action.owner, action.priority, action.status, action.business_area, action.source_snippet)


def _insight_text(insight):
    return _normalise_text(insight.title, insight.summary, insight.insight_type, insight.business_area, insight.severity, insight.why_it_matters, insight.buyer_relevance, insight.suggested_action)


def _categories_for_text(text):
    matched = []
    for category in DUE_DILIGENCE_CATEGORIES:
        if _contains_any(text, category["keywords"]):
            matched.append(category["slug"])
    return matched or ["legal-risk-governance"]


def _blank_category_summary(category, note=None):
    return {
        "slug": category["slug"],
        "name": category["name"],
        "expected_evidence": category["expected_evidence"],
        "documents": [],
        "analyses": [],
        "risks": [],
        "actions": [],
        "insights": [],
        "curated_evidence": [],
        "pinned_evidence": [],
        "excluded_evidence": [],
        "note": note,
        "counts": {
            "documents": 0,
            "analyses": 0,
            "risks": 0,
            "actions": 0,
            "insights": 0,
            "open_actions": 0,
            "high_risks": 0,
            "curated_evidence": 0,
            "pinned_evidence": 0,
            "excluded_evidence": 0,
        },
        "score": 0,
        "status": "Insufficient Evidence",
        "reason": "No material evidence has been linked to this category yet.",
        "missing_evidence": list(category["expected_evidence"]),
        "buyer_questions": [],
    }


def _unique_append(items, item, key="id", limit=30):
    item_key = item.get(key)
    if item_key is None:
        item_key = item.get("title") or item.get("name")

    if all((existing.get(key) if existing.get(key) is not None else existing.get("title") or existing.get("name")) != item_key for existing in items):
        items.append(item)

    if len(items) > limit:
        del items[limit:]


def _document_is_excluded(source_file_id, curation_by_doc_category, category_slug=None):
    if category_slug:
        evidence = curation_by_doc_category.get((source_file_id, category_slug))
        return bool(evidence and evidence.is_excluded)

    return any(evidence.is_excluded for (doc_id, _slug), evidence in curation_by_doc_category.items() if doc_id == source_file_id)


def _curation_item(evidence):
    document = evidence.source_file
    return {
        "id": evidence.id,
        "source_file_id": evidence.source_file_id,
        "title": document.original_filename if document else f"SourceFile {evidence.source_file_id}",
        "status": document.processing_status if document else None,
        "business_area": document.business_area if document else None,
        "category": document.document_category if document else None,
        "category_slug": evidence.category_slug,
        "evidence_strength": evidence.evidence_strength,
        "buyer_relevance": evidence.buyer_relevance,
        "is_pinned": evidence.is_pinned,
        "is_excluded": evidence.is_excluded,
        "management_note": evidence.management_note,
        "created_at": evidence.created_at,
        "updated_at": evidence.updated_at,
        "manual": True,
    }


def _score_category(summary):
    counts = summary["counts"]
    curated = summary.get("curated_evidence", [])
    pinned = summary.get("pinned_evidence", [])
    note = summary.get("note")

    evidence_points = min(35, counts["documents"] * 4 + counts["analyses"] * 5 + counts["insights"] * 3)
    action_points = min(15, counts["actions"] * 2)
    curation_points = 0

    for item in curated:
        strength = str(item.get("evidence_strength") or "").lower()
        relevance = str(item.get("buyer_relevance") or "").lower()
        curation_points += MANUAL_STRENGTH_POINTS.get(strength, 0)
        curation_points += BUYER_RELEVANCE_POINTS.get(relevance, 0)
        if item.get("is_pinned"):
            curation_points += 8

    curation_points = min(35, max(-20, curation_points))
    commentary_points = 8 if note and any([note.current_position, note.known_gaps, note.mitigating_actions, note.buyer_response_angle]) else 0

    risk_penalty = min(30, counts["high_risks"] * 8)
    open_action_penalty = min(15, counts["open_actions"] * 2)
    exclusion_penalty = min(12, counts["excluded_evidence"] * 2)

    score = max(0, min(100, 30 + evidence_points + action_points + curation_points + commentary_points - risk_penalty - open_action_penalty - exclusion_penalty))

    if counts["documents"] == 0 and counts["analyses"] == 0 and counts["curated_evidence"] == 0:
        status = "Insufficient Evidence"
        reason = "No source evidence has been identified for this due diligence category."
    elif counts["high_risks"] >= 3:
        status = "High Risk"
        reason = "Multiple high-severity risks are linked to this category and should be addressed before buyer review."
    elif score >= 75:
        status = "Strong"
        reason = "Evidence is curated or well-developed and this area is supportable for diligence."
    elif score >= 55:
        status = "Adequate"
        reason = "Useful evidence exists, but further curation, commentary or gap closure would strengthen buyer confidence."
    else:
        status = "Weak"
        reason = "Evidence exists but appears thin, incomplete, excluded, or risk-weighted."

    summary["score"] = score
    summary["status"] = status
    summary["reason"] = reason

    present_terms = _normalise_text(summary["documents"], summary["analyses"], summary["risks"], summary["actions"], summary["insights"], summary["curated_evidence"], note.current_position if note else "")
    missing = []
    for expected in summary["expected_evidence"]:
        words = [word.lower() for word in expected.replace("/", " ").split() if len(word) > 3]
        if not any(word in present_terms for word in words):
            missing.append(expected)
    summary["missing_evidence"] = missing

    return summary


def get_evidence_for_document(source_file_id):
    return (
        DueDiligenceEvidence.query
        .filter_by(source_file_id=source_file_id)
        .order_by(DueDiligenceEvidence.category_slug.asc())
        .all()
    )


def get_category_note(category_slug):
    return DueDiligenceCategoryNote.query.filter_by(category_slug=category_slug).first()


def build_due_diligence_library():
    notes = {note.category_slug: note for note in DueDiligenceCategoryNote.query.all()}
    summaries = {category["slug"]: _blank_category_summary(category, notes.get(category["slug"])) for category in DUE_DILIGENCE_CATEGORIES}

    curated_records = DueDiligenceEvidence.query.order_by(DueDiligenceEvidence.is_pinned.desc(), DueDiligenceEvidence.updated_at.desc()).all()
    curation_by_doc_category = {(record.source_file_id, record.category_slug): record for record in curated_records}

    for record in curated_records:
        if record.category_slug not in summaries:
            continue
        item = _curation_item(record)
        if record.is_excluded:
            _unique_append(summaries[record.category_slug]["excluded_evidence"], item, key="source_file_id", limit=50)
            continue
        _unique_append(summaries[record.category_slug]["curated_evidence"], item, key="source_file_id", limit=50)
        _unique_append(summaries[record.category_slug]["documents"], item, key="source_file_id", limit=50)
        if record.is_pinned:
            _unique_append(summaries[record.category_slug]["pinned_evidence"], item, key="source_file_id", limit=50)

    documents = SourceFile.query.order_by(SourceFile.created_at.desc()).limit(500).all()
    analyses = DocumentAnalysis.query.order_by(DocumentAnalysis.created_at.desc()).limit(500).all()
    risks = RiskFlag.query.order_by(RiskFlag.created_at.desc()).limit(500).all()
    actions = ActionItem.query.order_by(ActionItem.created_at.desc()).limit(500).all()
    insights = Insight.query.order_by(Insight.created_at.desc()).limit(500).all()

    for document in documents:
        item = {
            "id": document.id,
            "source_file_id": document.id,
            "title": document.original_filename,
            "status": document.processing_status,
            "business_area": document.business_area,
            "category": document.document_category,
            "created_at": document.created_at,
            "manual": False,
        }
        for slug in _categories_for_text(_document_text(document)):
            if _document_is_excluded(document.id, curation_by_doc_category, slug):
                continue
            if (document.id, slug) in curation_by_doc_category:
                continue
            _unique_append(summaries[slug]["documents"], item, key="source_file_id", limit=30)

    for analysis in analyses:
        document = SourceFile.query.get(analysis.source_file_id) if analysis.source_file_id else None
        if _document_is_excluded(analysis.source_file_id, curation_by_doc_category):
            continue
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
        combined_text = _analysis_due_diligence_text(analysis) + " " + _document_text(document)
        for slug in _categories_for_text(combined_text):
            if _document_is_excluded(analysis.source_file_id, curation_by_doc_category, slug):
                continue
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
        if _document_is_excluded(risk.source_file_id, curation_by_doc_category):
            continue
        item = {"id": risk.id, "source_file_id": risk.source_file_id, "title": risk.title, "summary": risk.summary, "severity": risk.severity, "status": risk.status, "business_area": risk.business_area, "buyer_relevance": risk.buyer_relevance, "created_at": risk.created_at}
        for slug in _categories_for_text(_risk_text(risk)):
            _unique_append(summaries[slug]["risks"], item, limit=30)

    for action in actions:
        if _document_is_excluded(action.source_file_id, curation_by_doc_category):
            continue
        item = {"id": action.id, "source_file_id": action.source_file_id, "title": action.title, "description": action.description, "priority": action.priority, "status": action.status, "owner": action.owner, "business_area": action.business_area, "created_at": action.created_at}
        for slug in _categories_for_text(_action_text(action)):
            _unique_append(summaries[slug]["actions"], item, limit=30)

    for insight in insights:
        item = {"id": insight.id, "title": insight.title, "summary": insight.summary, "severity": insight.severity, "insight_type": insight.insight_type, "business_area": insight.business_area, "buyer_relevance": insight.buyer_relevance, "created_at": insight.created_at}
        for slug in _categories_for_text(_insight_text(insight)):
            _unique_append(summaries[slug]["insights"], item, limit=30)

    for summary in summaries.values():
        summary["counts"]["documents"] = len(summary["documents"])
        summary["counts"]["analyses"] = len(summary["analyses"])
        summary["counts"]["risks"] = len(summary["risks"])
        summary["counts"]["actions"] = len(summary["actions"])
        summary["counts"]["insights"] = len(summary["insights"])
        summary["counts"]["curated_evidence"] = len(summary["curated_evidence"])
        summary["counts"]["pinned_evidence"] = len(summary["pinned_evidence"])
        summary["counts"]["excluded_evidence"] = len(summary["excluded_evidence"])
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
        "curated_evidence": sum(c["counts"]["curated_evidence"] for c in categories),
        "pinned_evidence": sum(c["counts"]["pinned_evidence"] for c in categories),
        "excluded_evidence": sum(c["counts"]["excluded_evidence"] for c in categories),
        "overall_score": int(sum(c["score"] for c in categories) / max(1, len(categories))),
    }

    return {"categories": categories, "category_map": summaries, "totals": totals, "generated_at": datetime.now(timezone.utc)}


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
            gaps.append({"title": missing, "category_slug": category["slug"], "category": category["name"], "priority": priority, "status": "Open", "why_it_matters": f"Buyers may ask for clear evidence covering {missing.lower()} within {category['name']}.", "suggested_owner": "Executive / functional lead", "suggested_action": f"Upload or link current evidence for {missing.lower()} and rerun local AI review.", "linked_documents": category["documents"][:5]})
    gaps.sort(key=lambda item: ({"High": 0, "Medium": 1, "Low": 2}.get(item["priority"], 3), item["category"], item["title"]))
    return gaps


def build_buyer_questions(library=None):
    library = library or build_due_diligence_library()
    questions = []
    default_questions = {
        "People & Workforce": ["What is the current workforce risk profile and how is management addressing retention?", "Where is the evidence for training, compliance and management oversight?"],
        "Recruitment & Retention": ["What is the vacancy trend and how resilient is the recruitment pipeline?", "How dependent is the business on agency or hard-to-fill roles?"],
        "Contracts & Commercial": ["Which contracts, pricing terms or commercial dependencies could affect maintainable earnings?", "Where is the evidence for contract quality and renewal risk?"],
        "Operations & Service Delivery": ["What operational issues could affect continuity, quality or scalability?", "How strong is management visibility over service delivery?"],
        "Finance & Cost Pressure": ["What cost pressures could affect EBITDA quality or margin sustainability?", "Where is the evidence for pay, cost and forecast assumptions?"],
        "Compliance & Regulation": ["What compliance risks are open and what evidence supports mitigation?", "Where is the latest policy, audit or regulatory evidence?"],
        "Technology & Systems": ["Which systems are business-critical and how is technology risk controlled?", "Where is the evidence for data security, backups and resilience?"],
        "Legal / Risk / Governance": ["What governance evidence supports board-level oversight and risk management?", "Are there legal, insurance or unresolved risk matters a buyer may challenge?"],
        "Growth Opportunities": ["What evidence supports the growth story and buyer upside?", "Which growth opportunities are proven versus aspirational?"],
        "Management Capability": ["How does the management team demonstrate grip, cadence and accountability?", "Where is the evidence of decisions, ownership and follow-through?"],
    }
    for category in library["categories"]:
        for question in category["buyer_questions"]:
            questions.append({"question": question["title"], "category": category["name"], "category_slug": category["slug"], "recommended_angle": question.get("recommended_angle"), "source_file_id": question.get("source_file_id"), "evidence_count": category["counts"]["documents"] + category["counts"]["analyses"], "risk_count": category["counts"]["risks"], "gap_count": len(category["missing_evidence"])})
        for question in default_questions.get(category["name"], []):
            questions.append({"question": question, "category": category["name"], "category_slug": category["slug"], "recommended_angle": "Answer using linked evidence. If evidence is missing, treat this as a diligence gap before buyer engagement.", "source_file_id": None, "evidence_count": category["counts"]["documents"] + category["counts"]["analyses"], "risk_count": category["counts"]["risks"], "gap_count": len(category["missing_evidence"])})
    return questions[:80]


def build_executive_narrative(library=None):
    library = library or build_due_diligence_library()
    totals = library["totals"]
    strong = [c for c in library["categories"] if c["status"] in {"Strong", "Adequate"}]
    weak = [c for c in library["categories"] if c["status"] in {"Weak", "Insufficient Evidence"}]
    high_risk = [c for c in library["categories"] if c["status"] == "High Risk"]
    curated_count = totals.get("curated_evidence", 0)
    pinned_count = totals.get("pinned_evidence", 0)
    return {
        "headline": f"Current exit readiness score is {totals['overall_score']}%, with {totals['strong']} strong area(s), {totals['adequate']} adequate area(s), {totals['high_risk']} high-risk area(s), {curated_count} curated evidence link(s), and {pinned_count} pinned key evidence item(s).",
        "what_has_improved": [f"{category['name']} has a {category['status'].lower()} evidence position with {category['counts']['documents']} document(s), {category['counts']['curated_evidence']} curated evidence link(s), and {category['counts']['pinned_evidence']} pinned item(s)." for category in strong[:5]],
        "risk_control": [f"{category['name']} needs management attention: {category['reason']}" for category in (high_risk + weak)[:6]],
        "buyer_story": ["The business is building a source-linked evidence trail rather than relying on unsupported narrative.", "Manual curation now allows management to pin key evidence, exclude noise, and shape buyer response angles.", "Daily extraction, local AI review and end-of-day executive briefings provide a repeatable diligence rhythm."],
        "next_focus": [f"Strengthen {category['name']} by uploading or curating evidence for: {', '.join(category['missing_evidence'][:3])}." for category in weak[:5] if category["missing_evidence"]],
    }
