from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Insight, InsightEvidence, utcnow

insights_bp = Blueprint("insights", __name__, url_prefix="/insights")


@insights_bp.route("/")
@login_required
def index():
    items = Insight.query.order_by(Insight.created_at.desc()).all()
    return render_template("insights/index.html", insights=items)


@insights_bp.route("/<int:insight_id>")
@login_required
def detail(insight_id):
    insight = Insight.query.get_or_404(insight_id)
    evidence_items = (
        InsightEvidence.query
        .filter_by(insight_id=insight.id)
        .order_by(InsightEvidence.created_at.desc())
        .all()
    )
    return render_template("insights/detail.html", insight=insight, evidence_items=evidence_items)


@insights_bp.route("/<int:insight_id>/status/<status>", methods=["POST"])
@login_required
def update_status(insight_id, status):
    insight = Insight.query.get_or_404(insight_id)

    allowed = {"open", "monitoring", "closed", "dismissed"}
    if status not in allowed:
        flash("Invalid insight status.", "error")
        return redirect(url_for("insights.detail", insight_id=insight.id))

    insight.status = status
    insight.updated_at = utcnow()
    db.session.commit()

    flash("Insight status updated.", "success")
    return redirect(url_for("insights.detail", insight_id=insight.id))
