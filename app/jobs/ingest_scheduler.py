import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import (
    AIProcessingRun,
    ActionItem,
    DocumentAnalysis,
    DocumentChunk,
    InsightEvidence,
    ProcessingLog,
    RiskFlag,
    SourceFile,
    utcnow,
)
from app.services.extraction import extract_source_file
from app.services.folder_ingest import scan_ingest_folder
from app.services.queueing import enqueue_local_ai_review


EMAIL_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".ico",
    ".tif",
    ".tiff",
}

AI_BUSY_STATUSES = {
    "local_ai_queued",
    "local_ai_reviewing",
}

AI_COMPLETE_STATUSES = {
    "local_ai_complete",
    "records_created",
}


def _bool_env(name, default="true"):
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


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


def _delete_file_if_safe(path_value):
    if not path_value:
        return

    try:
        path = Path(path_value)
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def _is_email_image_attachment(document):
    file_ext = (document.file_ext or "").lower()

    return (
        document.source_type == "email_attachment"
        and document.parent_file_id is not None
        and file_ext in EMAIL_IMAGE_EXTENSIONS
    )


def _delete_source_file_and_disk(document):
    storage_path = document.storage_path

    extracted_text_path = None
    body_html_path = None

    if document.document_text and document.document_text.extracted_text_path:
        extracted_text_path = document.document_text.extracted_text_path

    if document.email_message and document.email_message.body_html_path:
        body_html_path = document.email_message.body_html_path

    DocumentAnalysis.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
    DocumentChunk.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
    AIProcessingRun.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
    InsightEvidence.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)

    ActionItem.query.filter_by(source_file_id=document.id).update(
        {"source_file_id": None},
        synchronize_session=False,
    )
    RiskFlag.query.filter_by(source_file_id=document.id).update(
        {"source_file_id": None},
        synchronize_session=False,
    )

    db.session.delete(document)
    db.session.flush()

    _delete_file_if_safe(storage_path)
    _delete_file_if_safe(extracted_text_path)
    _delete_file_if_safe(body_html_path)


def cleanup_email_image_attachments():
    documents = (
        SourceFile.query
        .filter(
            SourceFile.source_type == "email_attachment",
            SourceFile.parent_file_id.isnot(None),
            SourceFile.file_ext.in_(EMAIL_IMAGE_EXTENSIONS),
        )
        .order_by(SourceFile.created_at.asc())
        .all()
    )

    deleted = 0
    failed = 0

    for document in documents:
        try:
            if not _is_email_image_attachment(document):
                continue

            child_count = SourceFile.query.filter_by(parent_file_id=document.id).count()
            if child_count:
                failed += 1
                continue

            _delete_source_file_and_disk(document)
            deleted += 1
        except Exception:
            db.session.rollback()
            failed += 1

    db.session.commit()

    return {
        "deleted": deleted,
        "failed": failed,
    }


def process_uploaded_documents(limit=10):
    documents = (
        SourceFile.query
        .filter(SourceFile.processing_status.in_(["uploaded", "failed"]))
        .filter(SourceFile.parent_file_id.is_(None))
        .order_by(SourceFile.created_at.asc())
        .limit(limit)
        .all()
    )

    processed = 0
    failed = 0
    skipped = 0

    for document in documents:
        if (document.file_ext or "").lower() in EMAIL_IMAGE_EXTENSIONS:
            skipped += 1
            continue

        try:
            extract_source_file(document.id)
            processed += 1
        except Exception as exc:
            failed += 1
            try:
                _log(document.id, "auto_extraction", "failed", f"Scheduled extraction failed: {exc}")
                db.session.commit()
            except Exception:
                db.session.rollback()

    return {
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
    }


def _is_ai_queue_candidate(document):
    if document.parent_file_id is not None:
        return False

    if (document.file_ext or "").lower() in EMAIL_IMAGE_EXTENSIONS:
        return False

    if document.processing_status in AI_BUSY_STATUSES or document.processing_status in AI_COMPLETE_STATUSES:
        return False

    if document.processing_status not in {"extracted", "local_ai_failed"}:
        return False

    if not document.document_text or not document.document_text.text_preview:
        return False

    return True


def queue_local_ai_batch(limit=5):
    documents = (
        SourceFile.query
        .filter(SourceFile.processing_status.in_(["extracted", "local_ai_failed"]))
        .filter(SourceFile.parent_file_id.is_(None))
        .order_by(SourceFile.created_at.asc())
        .limit(100)
        .all()
    )

    queued = 0
    skipped = 0
    failed = 0

    for document in documents:
        if queued >= limit:
            break

        if not _is_ai_queue_candidate(document):
            skipped += 1
            continue

        try:
            job = enqueue_local_ai_review(document.id)
            document.processing_status = "local_ai_queued"
            document.processing_error = None

            _log(
                document.id,
                "local_ai_review",
                "queued",
                f"Queued local AI review job from scheduled workflow: {job.id}",
            )
            queued += 1
        except Exception as exc:
            failed += 1
            _log(
                document.id,
                "local_ai_review",
                "failed",
                f"Scheduled workflow could not queue local AI review: {exc}",
            )

    db.session.commit()

    return {
        "queued": queued,
        "skipped": skipped,
        "failed": failed,
    }


def run_workflow(queue_ai=False):
    app = create_app()

    with app.app_context():
        ingest_result = scan_ingest_folder(
            uploaded_by_id=None,
            business_area=None,
            move_after_ingest=True,
        )

        extraction_limit = max(1, _int_env("AUTO_EXTRACT_BATCH_SIZE", 10))
        extraction_result = process_uploaded_documents(limit=extraction_limit)

        cleanup_result = cleanup_email_image_attachments()

        ai_result = {
            "queued": 0,
            "skipped": 0,
            "failed": 0,
            "ran": False,
        }

        if queue_ai:
            ai_batch_size = max(1, _int_env("AUTO_AI_BATCH_SIZE", 5))
            ai_result = queue_local_ai_batch(limit=ai_batch_size)
            ai_result["ran"] = True

        timestamp = datetime.now(timezone.utc).isoformat()
        print(
            "[SignalDash ingest workflow] "
            f"{timestamp} "
            f"scanned={ingest_result.get('scanned', 0)} "
            f"ingested={ingest_result.get('ingested', 0)} "
            f"duplicates={ingest_result.get('duplicates', 0)} "
            f"rejected={ingest_result.get('rejected', 0)} "
            f"ingest_failed={ingest_result.get('failed', 0)} "
            f"extracted={extraction_result.get('processed', 0)} "
            f"extract_failed={extraction_result.get('failed', 0)} "
            f"images_deleted={cleanup_result.get('deleted', 0)} "
            f"image_delete_failed={cleanup_result.get('failed', 0)} "
            f"ai_batch_ran={ai_result.get('ran', False)} "
            f"ai_queued={ai_result.get('queued', 0)} "
            f"ai_failed={ai_result.get('failed', 0)}",
            flush=True,
        )

        return {
            "ingest": ingest_result,
            "extraction": extraction_result,
            "cleanup": cleanup_result,
            "ai": ai_result,
        }


def main():
    enabled = _bool_env("AUTO_INGEST_ENABLED", "true")
    interval_seconds = max(60, _int_env("AUTO_INGEST_INTERVAL_SECONDS", 900))
    ai_interval_seconds = max(interval_seconds, _int_env("AUTO_AI_INTERVAL_SECONDS", 1800))
    run_on_startup = _bool_env("AUTO_INGEST_RUN_ON_STARTUP", "true")
    auto_extract_enabled = _bool_env("AUTO_EXTRACT_ENABLED", "true")
    auto_ai_enabled = _bool_env("AUTO_AI_QUEUE_ENABLED", "true")

    print(
        "[SignalDash ingest workflow] starting "
        f"enabled={enabled} "
        f"interval_seconds={interval_seconds} "
        f"ai_interval_seconds={ai_interval_seconds} "
        f"run_on_startup={run_on_startup} "
        f"auto_extract_enabled={auto_extract_enabled} "
        f"auto_ai_enabled={auto_ai_enabled}",
        flush=True,
    )

    if not enabled:
        print("[SignalDash ingest workflow] disabled by AUTO_INGEST_ENABLED", flush=True)
        while True:
            time.sleep(3600)

    last_ai_run = 0

    if run_on_startup:
        try:
            should_queue_ai = auto_ai_enabled
            run_workflow(queue_ai=should_queue_ai)
            if should_queue_ai:
                last_ai_run = time.time()
        except Exception as exc:
            print(f"[SignalDash ingest workflow] startup workflow failed: {exc}", flush=True)

    while True:
        time.sleep(interval_seconds)

        try:
            now = time.time()
            should_queue_ai = auto_ai_enabled and (now - last_ai_run >= ai_interval_seconds)
            run_workflow(queue_ai=should_queue_ai)

            if should_queue_ai:
                last_ai_run = now
        except Exception as exc:
            print(f"[SignalDash ingest workflow] workflow failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
