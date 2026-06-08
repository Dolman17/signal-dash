from flask import Blueprint, render_template
from flask_login import login_required

from app.models import SourceFile, Insight, ActionItem, RiskFlag, AIProcessingRun
from app.services.due_diligence_service import (
    build_buyer_questions,
    build_due_diligence_library,
    build_evidence_gaps,
    build_executive_narrative,
)


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def index():
    total_documents = SourceFile.query.count()

    recent_documents = (
        SourceFile.query.order_by(SourceFile.created_at.desc())
        .limit(8)
        .all()
    )

    open_insights = Insight.query.filter_by(status="open").count()
    open_actions = ActionItem.query.filter_by(status="open").count()
    open_risks = RiskFlag.query.filter_by(status="open").count()

    recent_ai_runs = (
        AIProcessingRun.query.order_by(AIProcessingRun.created_at.desc())
        .limit(5)
        .all()
    )

    latest_insights = (
        Insight.query
        .filter_by(status="open")
        .order_by(Insight.created_at.desc())
        .limit(5)
        .all()
    )

    latest_risks = (
        RiskFlag.query
        .filter_by(status="open")
        .order_by(RiskFlag.created_at.desc())
        .limit(5)
        .all()
    )

    latest_actions = (
        ActionItem.query
        .filter_by(status="open")
        .order_by(ActionItem.created_at.desc())
        .limit(5)
        .all()
    )

    due_diligence = build_due_diligence_library()
    evidence_gaps = build_evidence_gaps(due_diligence)

    return render_template(
        "dashboard/index.html",
        total_documents=total_documents,
        recent_documents=recent_documents,
        open_insights=open_insights,
        open_actions=open_actions,
        open_risks=open_risks,
        recent_ai_runs=recent_ai_runs,
        latest_insights=latest_insights,
        latest_risks=latest_risks,
        latest_actions=latest_actions,
        due_diligence=due_diligence,
        evidence_gaps=evidence_gaps[:5],
    )


@dashboard_bp.route("/executive")
@login_required
def executive():
    due_diligence = build_due_diligence_library()
    narrative = build_executive_narrative(due_diligence)
    questions = build_buyer_questions(due_diligence)
    gaps = build_evidence_gaps(due_diligence)

    return render_template(
        "dashboard/executive.html",
        due_diligence=due_diligence,
        narrative=narrative,
        questions=questions[:5],
        gaps=gaps[:5],
    )


@dashboard_bp.route("/exit-readiness")
@login_required
def exit_readiness():
    due_diligence = build_due_diligence_library()
    narrative = build_executive_narrative(due_diligence)
    questions = build_buyer_questions(due_diligence)
    gaps = build_evidence_gaps(due_diligence)

    return render_template(
        "dashboard/exit_readiness.html",
        due_diligence=due_diligence,
        narrative=narrative,
        questions=questions[:8],
        gaps=gaps[:8],
    )
