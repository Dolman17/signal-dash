from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import DailyBriefing, SourceFile
from app.services.end_of_day_briefing import queue_placeholder
from app.services.queueing import enqueue_daily_briefing, enqueue_end_of_day_briefing

briefings_bp = Blueprint("briefings", __name__, url_prefix="/briefings")


def _parse_date(value):
    if not value:
        return date.today()

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return date.today()


def _source_documents_for_briefing(briefing):
    ids = briefing.source_file_ids_json or []
    if not ids:
        return []

    return (
        SourceFile.query
        .filter(SourceFile.id.in_(ids))
        .order_by(SourceFile.created_at.asc())
        .all()
    )


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

    if existing and existing.provider in {"queued", "running"}:
        flash("Daily briefing is already queued or running.", "info")
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
        existing.title = f"Daily Briefing - {briefing_date.isoformat()}"
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


@briefings_bp.route("/end-of-day")
@login_required
def end_of_day():
    selected_date = _parse_date(request.args.get("date"))

    briefings = (
        DailyBriefing.query
        .filter(DailyBriefing.title.ilike("End of Day Briefing%"))
        .order_by(DailyBriefing.briefing_date.desc())
        .limit(30)
        .all()
    )

    latest = (
        DailyBriefing.query
        .filter_by(briefing_date=selected_date)
        .first()
    )

    if latest and not (latest.title or "").startswith("End of Day Briefing"):
        latest = None

    if not latest:
        latest = briefings[0] if briefings else None

    today_briefing = DailyBriefing.query.filter_by(briefing_date=date.today()).first()
    source_documents = _source_documents_for_briefing(latest) if latest else []

    return render_template(
        "briefings/end_of_day.html",
        briefings=briefings,
        latest=latest,
        today_briefing=today_briefing,
        selected_date=selected_date,
        source_documents=source_documents,
        openai_enabled=bool(request.environ.get("OPENAI_API_KEY")) or False,
    )


@briefings_bp.route("/end-of-day/generate", methods=["POST"])
@login_required
def generate_end_of_day():
    briefing_date = _parse_date(request.form.get("briefing_date"))
    force_regenerate = request.form.get("force_regenerate") == "1"

    existing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()

    if existing and existing.provider in {"end_of_day_queued", "end_of_day_running"} and not force_regenerate:
        flash("End-of-day briefing is already queued or running.", "info")
        return redirect(url_for("briefings.end_of_day", date=briefing_date.isoformat()))

    queue_placeholder(briefing_date)
    job = enqueue_end_of_day_briefing(briefing_date)

    existing = DailyBriefing.query.filter_by(briefing_date=briefing_date).first()
    existing.provider = "end_of_day_queued"
    existing.model_name = f"worker job {job.id}"
    db.session.commit()

    flash("End-of-day GPT briefing queued. The briefing worker will generate it in the background.", "success")
    return redirect(url_for("briefings.end_of_day", date=briefing_date.isoformat()))
