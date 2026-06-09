from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import ActionItem, utcnow

actions_bp = Blueprint("actions", __name__, url_prefix="/actions")


def _normalise(value):
    return (value or "").strip().lower()


def _action_lane(action):
    status = _normalise(action.status)

    if status in {"done", "complete", "completed", "closed", "dismissed"}:
        return "complete"
    if status in {"in_progress", "in progress", "doing"}:
        return "in_progress"
    if status in {"blocked", "stuck"}:
        return "blocked"
    if not action.owner:
        return "needs_owner"
    return "new"


@actions_bp.route("/")
@login_required
def index():
    records = ActionItem.query.order_by(ActionItem.created_at.desc()).all()
    today = date.today()
    soon = today + timedelta(days=7)

    lanes = {
        "new": [],
        "needs_owner": [],
        "in_progress": [],
        "blocked": [],
        "complete": [],
    }

    for action in records:
        lanes[_action_lane(action)].append(action)

    open_actions = [action for action in records if _action_lane(action) != "complete"]
    overdue = [action for action in open_actions if action.due_date and action.due_date < today]
    due_soon = [action for action in open_actions if action.due_date and today <= action.due_date <= soon]

    stats = {
        "total": len(records),
        "open": len(open_actions),
        "overdue": len(overdue),
        "due_soon": len(due_soon),
        "no_owner": len(lanes["needs_owner"]),
        "high_priority": len([action for action in open_actions if _normalise(action.priority) in {"high", "urgent", "critical"}]),
        "complete": len(lanes["complete"]),
    }

    owners = sorted({action.owner for action in records if action.owner})

    return render_template(
        "actions/index.html",
        actions=records,
        lanes=lanes,
        stats=stats,
        overdue=overdue,
        due_soon=due_soon,
        owners=owners,
        today=today,
    )


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
