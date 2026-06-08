import os
import time
from datetime import datetime, timezone

from app import create_app
from app.services.folder_ingest import scan_ingest_folder


def _bool_env(name, default="true"):
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


def run_once():
    app = create_app()

    with app.app_context():
        result = scan_ingest_folder(
            uploaded_by_id=None,
            business_area=None,
            move_after_ingest=True,
        )

        timestamp = datetime.now(timezone.utc).isoformat()
        print(
            "[SignalDash ingest scheduler] "
            f"{timestamp} scanned={result.get('scanned', 0)} "
            f"ingested={result.get('ingested', 0)} "
            f"duplicates={result.get('duplicates', 0)} "
            f"rejected={result.get('rejected', 0)} "
            f"failed={result.get('failed', 0)}",
            flush=True,
        )

        return result


def main():
    enabled = _bool_env("AUTO_INGEST_ENABLED", "true")
    interval_seconds = max(60, _int_env("AUTO_INGEST_INTERVAL_SECONDS", 900))
    run_on_startup = _bool_env("AUTO_INGEST_RUN_ON_STARTUP", "true")

    print(
        "[SignalDash ingest scheduler] starting "
        f"enabled={enabled} interval_seconds={interval_seconds} run_on_startup={run_on_startup}",
        flush=True,
    )

    if not enabled:
        print("[SignalDash ingest scheduler] disabled by AUTO_INGEST_ENABLED", flush=True)
        while True:
            time.sleep(3600)

    if run_on_startup:
        try:
            run_once()
        except Exception as exc:
            print(f"[SignalDash ingest scheduler] startup scan failed: {exc}", flush=True)

    while True:
        time.sleep(interval_seconds)

        try:
            run_once()
        except Exception as exc:
            print(f"[SignalDash ingest scheduler] scan failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
