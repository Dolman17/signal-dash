import os
from pathlib import Path

import requests
from flask import Blueprint, current_app, render_template
from flask_login import login_required
from redis import Redis

from app.models import (
    ActionItem,
    DailyBriefing,
    DocumentAnalysis,
    Insight,
    RiskFlag,
    SourceFile,
)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


def _path_status(path_value):
    path = Path(path_value)

    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "writable": os.access(path, os.W_OK) if path.exists() else False,
    }


def _check_redis():
    redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379/0")

    result = {
        "url": redis_url,
        "ok": False,
        "message": "Not checked",
    }

    try:
        conn = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
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
    )