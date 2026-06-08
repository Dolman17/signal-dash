from datetime import date

from app import create_app
from app.services.briefing_service import generate_daily_briefing


def run_daily_briefing_job(target_date_iso=None):
    app = create_app()

    with app.app_context():
        target_date = None

        if target_date_iso:
            target_date = date.fromisoformat(target_date_iso)

        briefing = generate_daily_briefing(target_date=target_date)

        return {
            "briefing_id": briefing.id,
            "briefing_date": briefing.briefing_date.isoformat(),
            "title": briefing.title,
            "provider": briefing.provider,
            "model_name": briefing.model_name,
        }