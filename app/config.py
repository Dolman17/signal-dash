import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///signaldash_dev.sqlite3",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    STORAGE_ROOT = Path(os.getenv("SIGNALDASH_STORAGE_ROOT", "./local_storage")).resolve()
    INGEST_ROOT = Path(os.getenv("SIGNALDASH_INGEST_ROOT", "./local_ingest")).resolve()
    BACKUP_ROOT = Path(os.getenv("SIGNALDASH_BACKUP_ROOT", "./local_backups")).resolve()
    LOG_ROOT = Path(os.getenv("SIGNALDASH_LOG_ROOT", "./local_logs")).resolve()

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    LOCAL_TRIAGE_MODEL = os.getenv("LOCAL_TRIAGE_MODEL", "qwen2.5-coder:3b")
    LOCAL_EXTRACTION_MODEL = os.getenv("LOCAL_EXTRACTION_MODEL", "qwen2.5-coder:7b")
    LOCAL_SUMMARY_MODEL = os.getenv("LOCAL_SUMMARY_MODEL", "llama3.1:8b")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_ENABLED = os.getenv("OPENAI_ENABLED", "false").lower() == "true"
    OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")

    DAILY_AI_SOFT_LIMIT_USD = float(os.getenv("DAILY_AI_SOFT_LIMIT_USD", "2"))
    DAILY_AI_HARD_LIMIT_USD = float(os.getenv("DAILY_AI_HARD_LIMIT_USD", "10"))
    MONTHLY_AI_SOFT_LIMIT_USD = float(os.getenv("MONTHLY_AI_SOFT_LIMIT_USD", "30"))
    MONTHLY_AI_HARD_LIMIT_USD = float(os.getenv("MONTHLY_AI_HARD_LIMIT_USD", "100"))

    MAX_CONTENT_LENGTH = 250 * 1024 * 1024

    @staticmethod
    def ensure_local_directories(app):
        roots = [
            app.config["STORAGE_ROOT"],
            app.config["INGEST_ROOT"],
            app.config["BACKUP_ROOT"],
            app.config["LOG_ROOT"],
        ]

        for root in roots:
            root.mkdir(parents=True, exist_ok=True)

        storage_subdirs = [
            "originals",
            "attachments",
            "extracted_text",
            "previews",
            "exports",
        ]

        ingest_subdirs = [
            "incoming",
            "processing",
            "processed",
            "failed",
        ]

        for subdir in storage_subdirs:
            (app.config["STORAGE_ROOT"] / subdir).mkdir(parents=True, exist_ok=True)

        for subdir in ingest_subdirs:
            (app.config["INGEST_ROOT"] / subdir).mkdir(parents=True, exist_ok=True)
