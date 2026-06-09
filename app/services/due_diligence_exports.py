import csv
from io import StringIO

from app.services.due_diligence_service import (
    build_buyer_questions,
    build_due_diligence_library,
    build_evidence_gaps,
    build_executive_narrative,
)


def _csv_response(rows, fieldnames):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def build_board_pack_context():
    library = build_due_diligence_library()
    gaps = build_evidence_gaps(library)
    questions = build_buyer_questions(library)
    narrative = build_executive_narrative(library)

    return {
        "library": library,
        "gaps": gaps,
        "questions": questions,
        "narrative": narrative,
    }


def evidence_index_csv():
    library = build_due_diligence_library()
    rows = []

    for category in library["categories"]:
        for item in category.get("documents", []):
            rows.append(
                {
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "document_id": item.get("source_file_id") or item.get("id"),
                    "document_title": item.get("title"),
                    "processing_status": item.get("status"),
                    "business_area": item.get("business_area"),
                    "manual_curation": "Yes" if item.get("manual") else "No",
                    "evidence_strength": item.get("evidence_strength"),
                    "buyer_relevance": item.get("buyer_relevance"),
                    "pinned_key_evidence": "Yes" if item.get("is_pinned") else "No",
                    "excluded": "Yes" if item.get("is_excluded") else "No",
                    "management_note": item.get("management_note"),
                    "category_status": category.get("status"),
                    "category_score": category.get("score"),
                }
            )

        for item in category.get("excluded_evidence", []):
            rows.append(
                {
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "document_id": item.get("source_file_id") or item.get("id"),
                    "document_title": item.get("title"),
                    "processing_status": item.get("status"),
                    "business_area": item.get("business_area"),
                    "manual_curation": "Yes",
                    "evidence_strength": item.get("evidence_strength"),
                    "buyer_relevance": item.get("buyer_relevance"),
                    "pinned_key_evidence": "Yes" if item.get("is_pinned") else "No",
                    "excluded": "Yes",
                    "management_note": item.get("management_note"),
                    "category_status": category.get("status"),
                    "category_score": category.get("score"),
                }
            )

    return _csv_response(
        rows,
        [
            "category",
            "category_slug",
            "document_id",
            "document_title",
            "processing_status",
            "business_area",
            "manual_curation",
            "evidence_strength",
            "buyer_relevance",
            "pinned_key_evidence",
            "excluded",
            "management_note",
            "category_status",
            "category_score",
        ],
    )


def buyer_questions_csv():
    library = build_due_diligence_library()
    questions = build_buyer_questions(library)
    rows = []

    for question in questions:
        rows.append(
            {
                "category": question.get("category"),
                "category_slug": question.get("category_slug"),
                "question": question.get("question"),
                "recommended_angle": question.get("recommended_angle"),
                "source_file_id": question.get("source_file_id"),
                "evidence_count": question.get("evidence_count"),
                "risk_count": question.get("risk_count"),
                "gap_count": question.get("gap_count"),
            }
        )

    return _csv_response(
        rows,
        [
            "category",
            "category_slug",
            "question",
            "recommended_angle",
            "source_file_id",
            "evidence_count",
            "risk_count",
            "gap_count",
        ],
    )


def risk_gap_tracker_csv():
    library = build_due_diligence_library()
    gaps = build_evidence_gaps(library)
    rows = []

    for category in library["categories"]:
        for risk in category.get("risks", []):
            rows.append(
                {
                    "type": "Risk",
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "title": risk.get("title"),
                    "priority_or_severity": risk.get("severity"),
                    "status": risk.get("status"),
                    "owner": "",
                    "why_it_matters": risk.get("summary") or risk.get("buyer_relevance"),
                    "suggested_action": "Confirm mitigation, ownership and supporting evidence before buyer review.",
                    "source_file_id": risk.get("source_file_id"),
                }
            )

        for action in category.get("actions", []):
            rows.append(
                {
                    "type": "Action",
                    "category": category["name"],
                    "category_slug": category["slug"],
                    "title": action.get("title"),
                    "priority_or_severity": action.get("priority"),
                    "status": action.get("status"),
                    "owner": action.get("owner"),
                    "why_it_matters": action.get("description"),
                    "suggested_action": "Close or update the action before external diligence review.",
                    "source_file_id": action.get("source_file_id"),
                }
            )

    for gap in gaps:
        rows.append(
            {
                "type": "Evidence Gap",
                "category": gap.get("category"),
                "category_slug": gap.get("category_slug"),
                "title": gap.get("title"),
                "priority_or_severity": gap.get("priority"),
                "status": gap.get("status"),
                "owner": gap.get("suggested_owner"),
                "why_it_matters": gap.get("why_it_matters"),
                "suggested_action": gap.get("suggested_action"),
                "source_file_id": "",
            }
        )

    return _csv_response(
        rows,
        [
            "type",
            "category",
            "category_slug",
            "title",
            "priority_or_severity",
            "status",
            "owner",
            "why_it_matters",
            "suggested_action",
            "source_file_id",
        ],
    )


def category_narrative_csv():
    library = build_due_diligence_library()
    rows = []

    for category in library["categories"]:
        note = category.get("note")
        rows.append(
            {
                "category": category.get("name"),
                "category_slug": category.get("slug"),
                "score": category.get("score"),
                "status": category.get("status"),
                "reason": category.get("reason"),
                "documents": category["counts"].get("documents"),
                "curated_evidence": category["counts"].get("curated_evidence"),
                "pinned_evidence": category["counts"].get("pinned_evidence"),
                "high_risks": category["counts"].get("high_risks"),
                "open_actions": category["counts"].get("open_actions"),
                "missing_evidence": "; ".join(category.get("missing_evidence") or []),
                "current_position": note.current_position if note else "",
                "known_gaps": note.known_gaps if note else "",
                "mitigating_actions": note.mitigating_actions if note else "",
                "buyer_response_angle": note.buyer_response_angle if note else "",
            }
        )

    return _csv_response(
        rows,
        [
            "category",
            "category_slug",
            "score",
            "status",
            "reason",
            "documents",
            "curated_evidence",
            "pinned_evidence",
            "high_risks",
            "open_actions",
            "missing_evidence",
            "current_position",
            "known_gaps",
            "mitigating_actions",
            "buyer_response_angle",
        ],
    )
