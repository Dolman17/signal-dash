from app.extensions import db
from app.models import (
    ActionItem,
    DocumentAnalysis,
    DocumentChunk,
    Insight,
    InsightEvidence,
    ProcessingLog,
    RiskFlag,
    SourceFile,
    utcnow,
)


def _log(source_file_id, stage, status, message=None):
    entry = ProcessingLog(
        source_file_id=source_file_id,
        stage=stage,
        status=status,
        message=message,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.session.add(entry)


def _first_chunk(source_file_id):
    return (
        DocumentChunk.query
        .filter_by(source_file_id=source_file_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .first()
    )


def _clean(value, fallback=""):
    if value is None:
        return fallback

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _truncate(value, limit):
    value = _clean(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _normalise_json_list(value, default_key="title"):
    if not value:
        return []

    if isinstance(value, dict):
        return [value]

    if not isinstance(value, list):
        value = [value]

    normalised = []
    for item in value:
        if isinstance(item, dict):
            normalised.append(item)
        elif item is None:
            continue
        else:
            text = _clean(item)
            if text:
                normalised.append({default_key: text, "description": text, "summary": text})

    return normalised


def _normalise_dict(value):
    return value if isinstance(value, dict) else {}


def _normalise_analysis_json(analysis):
    analysis.actions_json = _normalise_json_list(analysis.actions_json, default_key="title")
    analysis.risks_json = _normalise_json_list(analysis.risks_json, default_key="title")
    analysis.opportunities_json = _normalise_json_list(analysis.opportunities_json, default_key="title")
    analysis.entities_json = _normalise_json_list(analysis.entities_json, default_key="name")
    analysis.buyer_questions_json = _normalise_json_list(analysis.buyer_questions_json, default_key="question")
    analysis.due_diligence_json = _normalise_dict(analysis.due_diligence_json)

    if analysis.due_diligence_json:
        analysis.due_diligence_json["evidence_gaps"] = _normalise_json_list(
            analysis.due_diligence_json.get("evidence_gaps"),
            default_key="gap",
        )
        analysis.due_diligence_json["likely_buyer_questions"] = _normalise_json_list(
            analysis.due_diligence_json.get("likely_buyer_questions"),
            default_key="question",
        )
        analysis.due_diligence_json["recommended_follow_up"] = _normalise_json_list(
            analysis.due_diligence_json.get("recommended_follow_up"),
            default_key="title",
        )

    return analysis


def _normalise_severity(value):
    value = _clean(value, "Amber").title()

    if value in ["Red", "Amber", "Green", "Blue"]:
        return value

    if value in ["High", "Critical", "Severe"]:
        return "Red"

    if value in ["Medium", "Moderate"]:
        return "Amber"

    if value in ["Low", "None"]:
        return "Green"

    return "Amber"


def _normalise_priority(value):
    value = _clean(value, "Medium").title()

    if value in ["High", "Medium", "Low"]:
        return value

    return "Medium"


def _normalise_confidence(value):
    value = _clean(value, "Medium").title()

    if value in ["High", "Medium", "Low"]:
        return value

    return "Medium"


def _action_exists(source_file_id, title):
    return ActionItem.query.filter_by(
        source_file_id=source_file_id,
        title=title,
        created_by_ai=True,
    ).first()


def _risk_exists(source_file_id, title):
    return RiskFlag.query.filter_by(
        source_file_id=source_file_id,
        title=title,
    ).first()


def _insight_exists(title, source_file_id):
    existing = Insight.query.filter_by(title=title).first()

    if not existing:
        return None

    evidence = InsightEvidence.query.filter_by(
        insight_id=existing.id,
        source_file_id=source_file_id,
    ).first()

    if evidence:
        return existing

    return None


def _create_evidence(insight, source_file, snippet=None):
    first_chunk = _first_chunk(source_file.id)

    existing = InsightEvidence.query.filter_by(
        insight_id=insight.id,
        source_file_id=source_file.id,
        document_chunk_id=first_chunk.id if first_chunk else None,
    ).first()

    if existing:
        return existing

    evidence = InsightEvidence(
        insight_id=insight.id,
        source_file_id=source_file.id,
        document_chunk_id=first_chunk.id if first_chunk else None,
        evidence_snippet=_truncate(snippet or "", 2000),
    )

    db.session.add(evidence)
    return evidence


def create_actions_from_analysis(source_file, analysis):
    created = 0
    skipped = 0

    actions = _normalise_json_list(analysis.actions_json, default_key="title")
    first_chunk = _first_chunk(source_file.id)

    for item in actions:
        title = _truncate(item.get("title") or item.get("action") or item.get("description") or "Untitled action", 300)

        if not title or title == "Untitled action":
            skipped += 1
            continue

        if _action_exists(source_file.id, title):
            skipped += 1
            continue

        action = ActionItem(
            title=title,
            description=_clean(item.get("description") or item.get("summary")),
            owner=_truncate(item.get("owner"), 255) or None,
            priority=_normalise_priority(item.get("priority")),
            status="open",
            business_area=source_file.business_area,
            source_file_id=source_file.id,
            document_chunk_id=first_chunk.id if first_chunk else None,
            source_snippet=_truncate(item.get("source_snippet"), 2000),
            created_by_ai=True,
            confidence="Medium",
        )

        db.session.add(action)
        created += 1

    return created, skipped


def create_risks_and_insights_from_analysis(source_file, analysis):
    created_risks = 0
    skipped_risks = 0
    created_insights = 0
    skipped_insights = 0

    risks = _normalise_json_list(analysis.risks_json, default_key="title")

    for item in risks:
        title = _truncate(item.get("title") or item.get("summary") or item.get("description") or "Untitled risk", 300)

        if not title or title == "Untitled risk":
            skipped_risks += 1
            skipped_insights += 1
            continue

        severity = _normalise_severity(item.get("severity"))
        confidence = _normalise_confidence(item.get("confidence"))
        business_area = _clean(item.get("business_area")) or source_file.business_area
        summary = _clean(item.get("why_it_matters")) or _clean(item.get("summary")) or _clean(item.get("description"))

        existing_risk = _risk_exists(source_file.id, title)

        if existing_risk:
            skipped_risks += 1
        else:
            risk = RiskFlag(
                title=title,
                risk_type="AI Extracted Risk",
                business_area=business_area,
                severity=severity,
                confidence=confidence,
                likelihood=None,
                impact=severity,
                valuation_impact="Unknown",
                buyer_relevance=_clean(item.get("buyer_relevance")),
                summary=summary,
                mitigation=None,
                owner=None,
                status="open",
                source_file_id=source_file.id,
            )

            db.session.add(risk)
            created_risks += 1

        insight_title = title

        if _insight_exists(insight_title, source_file.id):
            skipped_insights += 1
        else:
            insight = Insight(
                title=insight_title,
                insight_type="Risk",
                business_area=business_area,
                category="AI Extracted Risk",
                severity=severity,
                confidence=confidence,
                summary=summary,
                why_it_matters=_clean(item.get("why_it_matters")) or summary,
                buyer_relevance=_clean(item.get("buyer_relevance")),
                suggested_action=None,
                status="open",
                owner=None,
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
                trend="New",
            )

            db.session.add(insight)
            db.session.flush()

            _create_evidence(
                insight,
                source_file,
                snippet=item.get("source_snippet") or item.get("why_it_matters") or summary,
            )

            created_insights += 1

    return created_risks, skipped_risks, created_insights, skipped_insights


def create_opportunity_insights_from_analysis(source_file, analysis):
    created = 0
    skipped = 0

    opportunities = _normalise_json_list(analysis.opportunities_json, default_key="title")

    for item in opportunities:
        title = _truncate(item.get("title") or item.get("summary") or item.get("description") or "Untitled opportunity", 300)

        if not title or title == "Untitled opportunity":
            skipped += 1
            continue

        if _insight_exists(title, source_file.id):
            skipped += 1
            continue

        summary = _clean(item.get("why_it_matters")) or _clean(item.get("summary")) or _clean(item.get("description"))

        insight = Insight(
            title=title,
            insight_type="Opportunity",
            business_area=source_file.business_area,
            category=_clean(item.get("category")) or "AI Extracted Opportunity",
            severity="Blue",
            confidence="Medium",
            summary=summary,
            why_it_matters=_clean(item.get("why_it_matters")) or summary,
            buyer_relevance=_clean(item.get("buyer_relevance")),
            suggested_action=_clean(item.get("suggested_action")),
            status="open",
            owner=None,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
            trend="New",
        )

        db.session.add(insight)
        db.session.flush()

        _create_evidence(
            insight,
            source_file,
            snippet=item.get("source_snippet") or item.get("why_it_matters") or summary,
        )

        created += 1

    return created, skipped


def _join_list_items(items):
    values = []
    for item in _normalise_json_list(items, default_key="text"):
        values.append(
            _clean(
                item.get("title")
                or item.get("question")
                or item.get("gap")
                or item.get("text")
                or item.get("description")
                or item.get("summary")
            )
        )
    return "; ".join([value for value in values if value])


def create_due_diligence_insights_from_analysis(source_file, analysis):
    created = 0
    skipped = 0

    dd = _normalise_dict(analysis.due_diligence_json)

    if not dd:
        return created, skipped

    is_relevant = dd.get("is_relevant")
    buyer_interest = _clean(dd.get("buyer_interest_level"))

    relevant = is_relevant is True or str(is_relevant).lower() == "true"

    if not relevant and buyer_interest not in ["Medium", "High"]:
        return created, skipped

    title = f"Due diligence relevance identified: {source_file.original_filename}"
    title = _truncate(title, 300)

    if _insight_exists(title, source_file.id):
        return created, skipped + 1

    evidence_gaps = dd.get("evidence_gaps") or []
    likely_questions = dd.get("likely_buyer_questions") or []

    summary_parts = []

    category = _clean(dd.get("category")) or "Uncategorised"
    evidence_strength = _clean(dd.get("evidence_strength")) or "Unknown"

    summary_parts.append(f"Category: {category}.")
    summary_parts.append(f"Buyer interest level: {buyer_interest or 'Unknown'}.")
    summary_parts.append(f"Evidence strength: {evidence_strength}.")

    evidence_gap_text = _join_list_items(evidence_gaps)
    likely_question_text = _join_list_items(likely_questions)

    if evidence_gap_text:
        summary_parts.append("Evidence gaps: " + evidence_gap_text)

    if likely_question_text:
        summary_parts.append("Likely buyer questions: " + likely_question_text)

    severity = "Amber"

    if buyer_interest == "High":
        severity = "Red"
    elif buyer_interest == "Low":
        severity = "Green"

    insight = Insight(
        title=title,
        insight_type="Evidence Gap" if evidence_gap_text else "Due Diligence",
        business_area="PE Exit / Due Diligence",
        category=category,
        severity=severity,
        confidence="Medium",
        summary=" ".join(summary_parts),
        why_it_matters="This document may be relevant to PE exit readiness or buyer due diligence.",
        buyer_relevance="A buyer may request supporting evidence, clarification or trend data connected to this area.",
        suggested_action="Review the document and decide whether it should be added to the due diligence evidence library.",
        status="open",
        owner=None,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        trend="New",
    )

    db.session.add(insight)
    db.session.flush()

    _create_evidence(
        insight,
        source_file,
        snippet=analysis.summary or source_file.original_filename,
    )

    created += 1
    return created, skipped


def materialise_analysis_for_document(source_file_id):
    source_file = SourceFile.query.get(source_file_id)

    if not source_file:
        raise ValueError(f"SourceFile not found: {source_file_id}")

    analysis = DocumentAnalysis.query.filter_by(source_file_id=source_file.id).first()

    if not analysis:
        raise ValueError("No AI analysis exists for this document.")

    analysis = _normalise_analysis_json(analysis)

    created_actions, skipped_actions = create_actions_from_analysis(source_file, analysis)

    (
        created_risks,
        skipped_risks,
        created_risk_insights,
        skipped_risk_insights,
    ) = create_risks_and_insights_from_analysis(source_file, analysis)

    created_opportunity_insights, skipped_opportunity_insights = create_opportunity_insights_from_analysis(
        source_file,
        analysis,
    )

    created_dd_insights, skipped_dd_insights = create_due_diligence_insights_from_analysis(
        source_file,
        analysis,
    )

    source_file.processing_status = "records_created"
    source_file.processed_at = utcnow()

    _log(
        source_file.id,
        "materialise_ai",
        "success",
        (
            f"Created {created_actions} action(s), {created_risks} risk(s), "
            f"{created_risk_insights + created_opportunity_insights + created_dd_insights} insight(s). "
            f"Skipped {skipped_actions + skipped_risks + skipped_risk_insights + skipped_opportunity_insights + skipped_dd_insights} duplicate/empty item(s)."
        ),
    )

    db.session.commit()

    return {
        "created_actions": created_actions,
        "skipped_actions": skipped_actions,
        "created_risks": created_risks,
        "skipped_risks": skipped_risks,
        "created_insights": created_risk_insights + created_opportunity_insights + created_dd_insights,
        "skipped_insights": skipped_risk_insights + skipped_opportunity_insights + skipped_dd_insights,
    }


def materialise_all_reviewed_documents():
    analyses = DocumentAnalysis.query.order_by(DocumentAnalysis.created_at.asc()).all()

    totals = {
        "documents": 0,
        "created_actions": 0,
        "skipped_actions": 0,
        "created_risks": 0,
        "skipped_risks": 0,
        "created_insights": 0,
        "skipped_insights": 0,
        "failed": 0,
    }

    for analysis in analyses:
        try:
            result = materialise_analysis_for_document(analysis.source_file_id)
            totals["documents"] += 1
            totals["created_actions"] += result["created_actions"]
            totals["skipped_actions"] += result["skipped_actions"]
            totals["created_risks"] += result["created_risks"]
            totals["skipped_risks"] += result["skipped_risks"]
            totals["created_insights"] += result["created_insights"]
            totals["skipped_insights"] += result["skipped_insights"]
        except Exception as exc:
            db.session.rollback()
            totals["failed"] += 1
            message = f"Materialise failed for SourceFile {analysis.source_file_id}: {exc}"
            print(message, flush=True)
            try:
                _log(analysis.source_file_id, "materialise_ai", "failed", message)
                db.session.commit()
            except Exception:
                db.session.rollback()

    return totals
