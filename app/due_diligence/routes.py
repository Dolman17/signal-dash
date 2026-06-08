from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import DueDiligenceCategoryNote, DueDiligenceEvidence, SourceFile, utcnow
from app.services.due_diligence_service import (
    CATEGORY_BY_SLUG,
    DUE_DILIGENCE_CATEGORIES,
    build_buyer_questions,
    build_due_diligence_library,
    build_evidence_gaps,
    build_executive_narrative,
)


due_diligence_bp = Blueprint("due_diligence", __name__, url_prefix="/due-diligence")


def _checkbox_enabled(name):
    return request.form.get(name) in {"1", "true", "yes", "on"}


@due_diligence_bp.route("/")
@login_required
def index():
    library = build_due_diligence_library()
    gaps = build_evidence_gaps(library)
    questions = build_buyer_questions(library)
    narrative = build_executive_narrative(library)

    return render_template(
        "due_diligence/index.html",
        library=library,
        gaps=gaps[:8],
        questions=questions[:8],
        narrative=narrative,
    )


@due_diligence_bp.route("/category/<slug>")
@login_required
def category(slug):
    if slug not in CATEGORY_BY_SLUG:
        abort(404)

    library = build_due_diligence_library()
    category_summary = library["category_map"].get(slug)

    if not category_summary:
        abort(404)

    return render_template(
        "due_diligence/category.html",
        category=category_summary,
        library=library,
    )


@due_diligence_bp.route("/category/<slug>/note", methods=["POST"])
@login_required
def update_category_note(slug):
    if slug not in CATEGORY_BY_SLUG:
        abort(404)

    note = DueDiligenceCategoryNote.query.filter_by(category_slug=slug).first()
    if not note:
        note = DueDiligenceCategoryNote(category_slug=slug)
        db.session.add(note)

    note.current_position = request.form.get("current_position", "").strip() or None
    note.known_gaps = request.form.get("known_gaps", "").strip() or None
    note.mitigating_actions = request.form.get("mitigating_actions", "").strip() or None
    note.buyer_response_angle = request.form.get("buyer_response_angle", "").strip() or None
    note.updated_by_id = current_user.id
    note.updated_at = utcnow()

    db.session.commit()
    flash("Management commentary updated.", "success")
    return redirect(url_for("due_diligence.category", slug=slug))


@due_diligence_bp.route("/documents/<int:document_id>/curation", methods=["POST"])
@login_required
def update_document_curation(document_id):
    document = SourceFile.query.get_or_404(document_id)
    selected_categories = set(request.form.getlist("category_slug"))
    valid_categories = {category["slug"] for category in DUE_DILIGENCE_CATEGORIES}
    selected_categories = selected_categories.intersection(valid_categories)

    evidence_strength = request.form.get("evidence_strength", "").strip() or None
    buyer_relevance = request.form.get("buyer_relevance", "").strip() or None
    management_note = request.form.get("management_note", "").strip() or None
    is_pinned = _checkbox_enabled("is_pinned")
    is_excluded = _checkbox_enabled("is_excluded")

    existing_records = {
        record.category_slug: record
        for record in DueDiligenceEvidence.query.filter_by(source_file_id=document.id).all()
    }

    for slug in selected_categories:
        record = existing_records.get(slug)
        if not record:
            record = DueDiligenceEvidence(
                source_file_id=document.id,
                category_slug=slug,
                created_by_id=current_user.id,
            )
            db.session.add(record)

        record.evidence_strength = evidence_strength
        record.buyer_relevance = buyer_relevance
        record.management_note = management_note
        record.is_pinned = is_pinned
        record.is_excluded = is_excluded
        record.updated_by_id = current_user.id
        record.updated_at = utcnow()

    for slug, record in existing_records.items():
        if slug not in selected_categories:
            db.session.delete(record)

    db.session.commit()
    flash("Due diligence evidence curation updated.", "success")
    return redirect(url_for("documents.detail", document_id=document.id))


@due_diligence_bp.route("/scorecard")
@login_required
def scorecard():
    library = build_due_diligence_library()

    return render_template(
        "due_diligence/scorecard.html",
        library=library,
    )


@due_diligence_bp.route("/evidence-gaps")
@login_required
def evidence_gaps():
    library = build_due_diligence_library()
    gaps = build_evidence_gaps(library)

    return render_template(
        "due_diligence/evidence_gaps.html",
        library=library,
        gaps=gaps,
    )


@due_diligence_bp.route("/buyer-questions")
@login_required
def buyer_questions():
    library = build_due_diligence_library()
    questions = build_buyer_questions(library)

    return render_template(
        "due_diligence/buyer_questions.html",
        library=library,
        questions=questions,
    )


@due_diligence_bp.route("/executive-narrative")
@login_required
def executive_narrative():
    library = build_due_diligence_library()
    narrative = build_executive_narrative(library)

    return render_template(
        "due_diligence/executive_narrative.html",
        library=library,
        narrative=narrative,
    )
