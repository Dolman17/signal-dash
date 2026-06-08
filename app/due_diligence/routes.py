from flask import Blueprint, abort, render_template
from flask_login import login_required

from app.services.due_diligence_service import (
    CATEGORY_BY_SLUG,
    build_buyer_questions,
    build_due_diligence_library,
    build_evidence_gaps,
    build_executive_narrative,
)


due_diligence_bp = Blueprint("due_diligence", __name__, url_prefix="/due-diligence")


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
