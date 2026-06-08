from datetime import date

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import DailyBriefing
from app.services.queueing import enqueue_daily_briefing

briefings_bp = Blueprint("briefings", __name__, url_prefix="/briefings")


@briefings_bp.route("/daily")
@login_required
def daily():
    briefings = (
        DailyBriefing.query
        .order_by(DailyBriefing.briefing_date.desc())
        .limit(30)
        .all()
    )

    latest = briefings[0] if briefings else None

    return render_template(
        "briefings/daily.html",
        briefings=briefings,
        latest=latest,
    )


@briefings_bp.route("/daily/generate", methods=["POST"])
@login_required
def generate_daily():
    briefing_date = date.today()

    existing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if existing and existing.provider == "queued":
        flash("Daily briefing is already queued.", "info")
        return redirect(url_for("briefings.daily"))

    if existing and existing.provider == "running":
        flash("Daily briefing is already running.", "info")
        return redirect(url_for("briefings.daily"))

    if not existing:
        existing = DailyBriefing(
            briefing_date=briefing_date,
            title=f"Daily Briefing - {briefing_date.isoformat()}",
            executive_summary="Daily briefing queued. The worker will generate it in the background.",
            highlights_json=[],
            risks_json=[],
            opportunities_json=[],
            actions_json=[],
            exit_readiness_json={},
            source_file_ids_json=[],
            provider="queued",
            model_name="worker",
        )
        db.session.add(existing)
    else:
        existing.executive_summary = "Daily briefing queued. The worker will regenerate it in the background."
        existing.provider = "queued"
        existing.model_name = "worker"

    db.session.commit()

    job = enqueue_daily_briefing(briefing_date)

    existing.provider = "queued"
    existing.model_name = f"worker job {job.id}"
    db.session.commit()

    flash("Daily briefing queued. The worker will generate it in the background.", "success")
    return redirect(url_for("briefings.daily"))