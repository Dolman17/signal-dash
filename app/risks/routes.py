from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import RiskFlag, utcnow

risks_bp = Blueprint("risks", __name__, url_prefix="/risks")


def _normalise(value):
    return (value or "").strip().lower()


def _risk_lane(risk):
    severity = _normalise(risk.severity)
    status = _normalise(risk.status)

    if status in {"mitigated", "closed", "dismissed", "resolved"}:
        return "resolved"
    if severity in {"red", "critical", "high"}:
        return "red"
    if severity in {"amber", "medium", "moderate"}:
        return "amber"
    if severity in {"green", "low"}:
        return "green"
    return "unclassified"


@risks_bp.route("/")
@login_required
def index():
    risks = RiskFlag.query.order_by(RiskFlag.created_at.desc()).all()

    lanes = {
        "red": [],
        "amber": [],
        "green": [],
        "unclassified": [],
        "resolved": [],
    }

    for risk in risks:
        lanes[_risk_lane(risk)].append(risk)

    stats = {
        "total": len(risks),
        "red": len(lanes["red"]),
        "amber": len(lanes["amber"]),
        "green": len(lanes["green"]),
        "unclassified": len(lanes["unclassified"]),
        "resolved": len(lanes["resolved"]),
        "no_owner": len([risk for risk in risks if not risk.owner]),
        "buyer_relevant": len([risk for risk in risks if risk.buyer_relevance]),
    }

    business_areas = sorted({risk.business_area for risk in risks if risk.business_area})

    return render_template(
        "risks/index.html",
        risks=risks,
        lanes=lanes,
        stats=stats,
        business_areas=business_areas,
    )


@risks_bp.route("/<int:risk_id>")
@login_required
def detail(risk_id):
    risk = RiskFlag.query.get_or_404(risk_id)
    return render_template("risks/detail.html", risk=risk)


@risks_bp.route("/<int:risk_id>/status/<status>", methods=["POST"])
@login_required
def update_status(risk_id, status):
    risk = RiskFlag.query.get_or_404(risk_id)
    allowed = {"open", "monitoring", "mitigated", "closed", "dismissed"}
    if status not in allowed:
        flash("Invalid status.", "error")
        return redirect(url_for("risks.detail", risk_id=risk.id))
    risk.status = status
    risk.updated_at = utcnow()
    db.session.commit()
    flash("Risk status updated.", "success")
    return redirect(url_for("risks.detail", risk_id=risk.id))
