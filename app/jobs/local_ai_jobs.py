from app import create_app
from app.extensions import db
from app.models import ProcessingLog, SourceFile, utcnow
from app.services.local_ai import run_full_local_ai_review


def _log(source_file_id, stage, status, message=None):
    entry = ProcessingLog(
        source_file_id=source_file_id,
        stage=stage,
        status=status,
        message=message,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.session.add(entry)


def run_local_ai_review_job(source_file_id: int):
    """
    Background RQ job for local Ollama document review.

    This creates its own Flask app context because RQ workers run outside
    the normal web request lifecycle.
    """
    app = create_app()

    with app.app_context():
        source_file = SourceFile.query.get(source_file_id)

        if not source_file:
            return {
                "status": "failed",
                "message": f"SourceFile not found: {source_file_id}",
            }

        try:
            source_file.processing_status = "local_ai_reviewing"
            source_file.processing_error = None

            _log(
                source_file.id,
                "local_ai_review",
                "started",
                "Background local AI review started.",
            )

            db.session.commit()

            analysis = run_full_local_ai_review(source_file.id)

            source_file = SourceFile.query.get(source_file_id)
            source_file.processing_status = "local_ai_complete"
            source_file.processing_error = None
            source_file.processed_at = utcnow()

            _log(
                source_file.id,
                "local_ai_review",
                "success",
                "Background local AI review completed.",
            )

            db.session.commit()

            return {
                "status": "success",
                "source_file_id": source_file.id,
                "analysis_id": analysis.id,
            }

        except Exception as exc:
            db.session.rollback()

            source_file = SourceFile.query.get(source_file_id)

            if source_file:
                source_file.processing_status = "local_ai_failed"
                source_file.processing_error = str(exc)

                _log(
                    source_file.id,
                    "local_ai_review",
                    "failed",
                    str(exc),
                )

                db.session.commit()

            return {
                "status": "failed",
                "source_file_id": source_file_id,
                "error": str(exc),
            }
