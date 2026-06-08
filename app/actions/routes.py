from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import ActionItem, utcnow

actions_bp = Blueprint("actions", __name__, url_prefix="/actions")


@actions_bp.route("/")
@login_required
def index():
    records = ActionItem.query.order_by(ActionItem.created_at.desc()).all()
    return render_template("actions/index.html", actions=records)


@actions_bp.route("/<int:action_id>")
@login_required
def detail(action_id):
    record = ActionItem.query.get_or_404(action_id)
    return render_template("actions/detail.html", action=record)


@actions_bp.route("/<int:action_id>/status/<status>", methods=["POST"])
@login_required
def update_status(action_id, status):
    record = ActionItem.query.get_or_404(action_id)
    allowed = {"open", "in_progress", "done", "dismissed"}
    if status not in allowed:
        flash("Invalid status.", "error")
        return redirect(url_for("actions.detail", action_id=record.id))
    record.status = status
    record.updated_at = utcnow()
    record.completed_at = utcnow() if status == "done" else None
    db.session.commit()
    flash("Status updated.", "success")
    return redirect(url_for("actions.detail", action_id=record.id))
