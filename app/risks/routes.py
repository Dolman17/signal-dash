from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import RiskFlag, utcnow

risks_bp = Blueprint("risks", __name__, url_prefix="/risks")


@risks_bp.route("/")
@login_required
def index():
    risks = RiskFlag.query.order_by(RiskFlag.created_at.desc()).all()
    return render_template("risks/index.html", risks=risks)


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
