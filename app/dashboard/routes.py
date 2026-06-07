from flask import Blueprint, render_template
from flask_login import login_required

from app.models import SourceFile, Insight, ActionItem, RiskFlag, AIProcessingRun

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
    )


@dashboard_bp.route("/executive")
@login_required
def executive():
    return render_template("dashboard/executive.html")


@dashboard_bp.route("/exit-readiness")
@login_required
def exit_readiness():
    return render_template("dashboard/exit_readiness.html")
