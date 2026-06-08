import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from redis import Redis
from rq import Queue
from rq.registry import (
    DeferredJobRegistry,
    FailedJobRegistry,
    FinishedJobRegistry,
    ScheduledJobRegistry,
    StartedJobRegistry,
)

from app.extensions import db
from app.models import (
    ActionItem,
    DailyBriefing,
    DocumentAnalysis,
    Insight,
    ProcessingLog,
    RiskFlag,
    SourceFile,
    utcnow,
)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


AI_QUEUE_NAMES = [
    "local_ai",
    "briefings",
    "cloud_ai",
    "ingest",
    "default",
]

QUEUE_OWNERS = {
    "local_ai": "signaldash-worker",
    "ingest": "signaldash-worker",
    "default": "signaldash-worker",
    "briefings": "signaldash-briefing-worker",
    "cloud_ai": "signaldash-briefing-worker",
}

QUEUE_ESTIMATED_MINUTES = {
    "local_ai": 5,
    "briefings": 2,
    "cloud_ai": 3,
    "ingest": 1,
    "default": 1,
}

WORKFLOW_CONTROL_KEYS = {
    "auto_ingest": "signaldash:auto_ingest_enabled",
    "auto_extract": "signaldash:auto_extract_enabled",
    "auto_ai": "signaldash:auto_ai_queue_enabled",
}


SOURCE_FILE_RE = re.compile(r"SourceFile\s+(\d+)", re.IGNORECASE)


def _path_status(path_value):
    path = Path(path_value)

    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "writable": os.access(path, os.W_OK) if path.exists() else False,
    }


def _redis_connection():
    redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)


def _check_redis():
    redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379/0")

    result = {
        "url": redis_url,
        "ok": False,
        "message": "Not checked",
    }

    try:
        conn = _redis_connection()
        pong = conn.ping()
        result["ok"] = bool(pong)
        result["message"] = "Connected" if pong else "No PONG response"
    except Exception as exc:
        result["message"] = str(exc)

    return result


def _check_ollama():
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

    result = {
        "url": base_url,
        "ok": False,
        "message": "Not checked",
        "models": [],
    }

    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()

        data = response.json()
        models = data.get("models", [])

        result["ok"] = True
        result["message"] = "Connected"
        result["models"] = [
            {
                "name": model.get("name"),
                "size": model.get("size"),
                "modified_at": model.get("modified_at"),
            }
            for model in models
        ]

    except Exception as exc:
        result["message"] = str(exc)

    return result


def _format_dt(value):
    if not value:
        return None

    try:
        return value.strftime("%d %b %Y %H:%M:%S")
    except Exception:
        return str(value)


def _age_minutes(value):
    if not value:
        return None

    try:
        now = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0, int((now - value).total_seconds() // 60))
    except Exception:
        return None


def _source_file_id_from_job(job):
    try:
        for arg in job.args or []:
            if isinstance(arg, int):
                return arg
            if isinstance(arg, str) and arg.isdigit():
                return int(arg)
    except Exception:
        pass

    text = " ".join(
        str(part or "")
        for part in [
            getattr(job, "description", ""),
            getattr(job, "func_name", ""),
        ]
    )
    match = SOURCE_FILE_RE.search(text)

    if match:
        return int(match.group(1))

    return None


def _safe_job_meta(job):
    if not job:
        return {}

    try:
        status = job.get_status(refresh=False)
    except Exception:
        status = "unknown"

    created_age = _age_minutes(job.created_at)
    enqueued_age = _age_minutes(job.enqueued_at)
    started_age = _age_minutes(job.started_at)

    return {
        "id": job.id,
        "status": status,
        "description": job.description or "",
        "func_name": job.func_name or "",
        "origin": job.origin or "",
        "created_at": _format_dt(job.created_at),
        "enqueued_at": _format_dt(job.enqueued_at),
        "started_at": _format_dt(job.started_at),
        "ended_at": _format_dt(job.ended_at),
        "created_age_minutes": created_age,
        "enqueued_age_minutes": enqueued_age,
        "started_age_minutes": started_age,
        "timeout": job.timeout,
        "result_ttl": job.result_ttl,
        "failure_ttl": job.failure_ttl,
        "exc_info": (job.exc_info or "")[:1200],
        "source_file_id": _source_file_id_from_job(job),
    }


def _jobs_from_ids(queue, job_ids, limit=10):
    jobs = []

    for job_id in job_ids[:limit]:
        try:
            job = queue.fetch_job(job_id)
            if job:
                jobs.append(_safe_job_meta(job))
        except Exception:
            continue

    return jobs


def _queue_snapshot(queue_name):
    conn = _redis_connection()
    queue = Queue(queue_name, connection=conn)

    started_registry = StartedJobRegistry(queue=queue)
    failed_registry = FailedJobRegistry(queue=queue)
    finished_registry = FinishedJobRegistry(queue=queue)
    deferred_registry = DeferredJobRegistry(queue=queue)
    scheduled_registry = ScheduledJobRegistry(queue=queue)

    queued_jobs = []
    try:
        queued_jobs = [_safe_job_meta(job) for job in queue.get_jobs(offset=0, length=10)]
    except Exception:
        queued_jobs = []

    started_ids = started_registry.get_job_ids()
    failed_ids = failed_registry.get_job_ids()
    finished_ids = finished_registry.get_job_ids()
    deferred_ids = deferred_registry.get_job_ids()
    scheduled_ids = scheduled_registry.get_job_ids()

    oldest_queued_age = None
    if queued_jobs:
        ages = [job.get("enqueued_age_minutes") for job in queued_jobs if job.get("enqueued_age_minutes") is not None]
        oldest_queued_age = max(ages) if ages else None

    estimated_minutes_per_job = QUEUE_ESTIMATED_MINUTES.get(queue_name, 2)
    estimated_backlog_minutes = queue.count * estimated_minutes_per_job

    return {
        "name": queue_name,
        "owner": QUEUE_OWNERS.get(queue_name, "general worker"),
        "estimated_minutes_per_job": estimated_minutes_per_job,
        "estimated_backlog_minutes": estimated_backlog_minutes,
        "oldest_queued_age_minutes": oldest_queued_age,
        "counts": {
            "queued": queue.count,
            "started": len(started_ids),
            "failed": len(failed_ids),
            "finished": len(finished_ids),
            "deferred": len(deferred_ids),
            "scheduled": len(scheduled_ids),
        },
        "queued_jobs": queued_jobs,
        "started_jobs": _jobs_from_ids(queue, started_ids, limit=10),
        "failed_jobs": _jobs_from_ids(queue, failed_ids, limit=10),
        "finished_jobs": _jobs_from_ids(queue, finished_ids, limit=10),
        "deferred_jobs": _jobs_from_ids(queue, deferred_ids, limit=10),
        "scheduled_jobs": _jobs_from_ids(queue, scheduled_ids, limit=10),
    }


def _ai_queue_overview():
    redis_status = _check_redis()

    overview = {
        "redis_status": redis_status,
        "queues": [],
        "total_counts": {
            "queued": 0,
            "started": 0,
            "failed": 0,
            "finished": 0,
            "deferred": 0,
            "scheduled": 0,
        },
        "total_estimated_backlog_minutes": 0,
        "error": None,
    }

    if not redis_status["ok"]:
        overview["error"] = redis_status["message"]
        return overview

    try:
        for queue_name in AI_QUEUE_NAMES:
            snapshot = _queue_snapshot(queue_name)
            overview["queues"].append(snapshot)
            overview["total_estimated_backlog_minutes"] += snapshot.get("estimated_backlog_minutes", 0)

            for key in overview["total_counts"].keys():
                overview["total_counts"][key] += snapshot["counts"].get(key, 0)

    except Exception as exc:
        overview["error"] = str(exc)

    return overview


def _workflow_controls():
    conn = _redis_connection()

    def read_flag(key, default=True):
        value = conn.get(key)
        if value is None:
            return default
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    return {
        "auto_ingest": read_flag(WORKFLOW_CONTROL_KEYS["auto_ingest"], True),
        "auto_extract": read_flag(WORKFLOW_CONTROL_KEYS["auto_extract"], True),
        "auto_ai": read_flag(WORKFLOW_CONTROL_KEYS["auto_ai"], True),
        "env": {
            "AUTO_INGEST_INTERVAL_SECONDS": os.getenv("AUTO_INGEST_INTERVAL_SECONDS", "900"),
            "AUTO_EXTRACT_BATCH_SIZE": os.getenv("AUTO_EXTRACT_BATCH_SIZE", "10"),
            "AUTO_AI_INTERVAL_SECONDS": os.getenv("AUTO_AI_INTERVAL_SECONDS", "1800"),
            "AUTO_AI_BATCH_SIZE": os.getenv("AUTO_AI_BATCH_SIZE", "5"),
        },
    }


@settings_bp.route("/")
@login_required
def index():
    storage_paths = {
        "Storage root": _path_status(current_app.config["STORAGE_ROOT"]),
        "Ingest root": _path_status(current_app.config["INGEST_ROOT"]),
        "Backup root": _path_status(current_app.config["BACKUP_ROOT"]),
        "Log root": _path_status(current_app.config["LOG_ROOT"]),
    }

    model_settings = {
        "Triage model": current_app.config.get("LOCAL_TRIAGE_MODEL"),
        "Extraction model": current_app.config.get("LOCAL_EXTRACTION_MODEL"),
        "Summary model": current_app.config.get("LOCAL_SUMMARY_MODEL"),
        "OpenAI enabled": current_app.config.get("OPENAI_ENABLED"),
        "OpenAI default model": current_app.config.get("OPENAI_DEFAULT_MODEL"),
    }

    app_settings = {
        "Database URL": current_app.config.get("SQLALCHEMY_DATABASE_URI"),
        "Redis URL": current_app.config.get("REDIS_URL"),
        "Ollama URL": current_app.config.get("OLLAMA_BASE_URL"),
        "Max upload size MB": int(current_app.config.get("MAX_CONTENT_LENGTH", 0) / 1024 / 1024),
        "Daily AI soft limit USD": current_app.config.get("DAILY_AI_SOFT_LIMIT_USD"),
        "Daily AI hard limit USD": current_app.config.get("DAILY_AI_HARD_LIMIT_USD"),
        "Monthly AI soft limit USD": current_app.config.get("MONTHLY_AI_SOFT_LIMIT_USD"),
        "Monthly AI hard limit USD": current_app.config.get("MONTHLY_AI_HARD_LIMIT_USD"),
    }

    record_counts = {
        "Documents": SourceFile.query.count(),
        "AI analyses": DocumentAnalysis.query.count(),
        "Insights": Insight.query.count(),
        "Risks": RiskFlag.query.count(),
        "Actions": ActionItem.query.count(),
        "Daily briefings": DailyBriefing.query.count(),
    }

    return render_template(
        "settings/index.html",
        redis_status=_check_redis(),
        ollama_status=_check_ollama(),
        storage_paths=storage_paths,
        model_settings=model_settings,
        app_settings=app_settings,
        record_counts=record_counts,
        workflow_controls=_workflow_controls() if _check_redis()["ok"] else None,
    )


@settings_bp.route("/ai-queue")
@login_required
def ai_queue():
    return render_template(
        "settings/ai_queue.html",
        queue_overview=_ai_queue_overview(),
        queue_names=AI_QUEUE_NAMES,
        workflow_controls=_workflow_controls(),
    )


@settings_bp.route("/ai-queue/<queue_name>/<job_id>/requeue", methods=["POST"])
@login_required
def requeue_failed_job(queue_name, job_id):
    if queue_name not in AI_QUEUE_NAMES:
        flash("Unknown queue.", "error")
        return redirect(url_for("settings.ai_queue"))

    try:
        conn = _redis_connection()
        queue = Queue(queue_name, connection=conn)
        failed_registry = FailedJobRegistry(queue=queue)
        failed_registry.requeue(job_id)
        flash(f"Requeued failed job {job_id} on {queue_name}.", "success")
    except Exception as exc:
        flash(f"Could not requeue failed job: {exc}", "error")

    return redirect(url_for("settings.ai_queue"))


@settings_bp.route("/ai-queue/<queue_name>/<job_id>/clear-started", methods=["POST"])
@login_required
def clear_started_job(queue_name, job_id):
    if queue_name not in AI_QUEUE_NAMES:
        flash("Unknown queue.", "error")
        return redirect(url_for("settings.ai_queue"))

    try:
        conn = _redis_connection()
        queue = Queue(queue_name, connection=conn)
        started_registry = StartedJobRegistry(queue=queue)
        job = queue.fetch_job(job_id)

        if not job:
            flash("Job was not found.", "error")
            return redirect(url_for("settings.ai_queue"))

        source_file_id = _source_file_id_from_job(job)
        started_registry.remove(job, delete_job=False)
        job.set_status("failed")
        job.exc_info = "Marked failed manually from SignalDesk AI Queue because it was stale/abandoned."
        job.save()

        if source_file_id:
            document = SourceFile.query.get(source_file_id)
            if document and document.processing_status in {"local_ai_queued", "local_ai_reviewing"}:
                document.processing_status = "local_ai_failed"
                document.processing_error = "Local AI job was marked stale/abandoned from the AI Queue screen."
                db.session.add(
                    ProcessingLog(
                        source_file_id=document.id,
                        stage="local_ai_review",
                        status="failed",
                        message="Marked stale/abandoned from AI Queue screen.",
                        started_at=utcnow(),
                        finished_at=utcnow(),
                    )
                )
                db.session.commit()

        flash(f"Cleared stale started job {job_id} from {queue_name}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not clear started job: {exc}", "error")

    return redirect(url_for("settings.ai_queue"))


@settings_bp.route("/workflow-control", methods=["POST"])
@login_required
def workflow_control():
    control = request.form.get("control", "").strip()
    enabled = request.form.get("enabled", "").strip().lower() == "true"

    if control not in WORKFLOW_CONTROL_KEYS:
        flash("Unknown workflow control.", "error")
        return redirect(url_for("settings.ai_queue"))

    try:
        conn = _redis_connection()
        conn.set(WORKFLOW_CONTROL_KEYS[control], "true" if enabled else "false")
        state = "enabled" if enabled else "paused"
        flash(f"{control.replace('_', ' ').title()} {state}.", "success")
    except Exception as exc:
        flash(f"Could not update workflow control: {exc}", "error")

    return redirect(request.form.get("next") or url_for("settings.ai_queue"))
