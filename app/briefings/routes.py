from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.models import DailyBriefing
from app.services.briefing_service import generate_daily_briefing

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
    briefing = generate_daily_briefing()
    flash("Daily briefing generated.", "success")
    return redirect(url_for("briefings.daily"))