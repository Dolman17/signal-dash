import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models import ProcessingLog, SourceFile, utcnow
from app.upload.routes import ALLOWED_EXTENSIONS


SYSTEM_FOLDER_NAMES = {
    "_processed",
    "_duplicates",
    "_rejected",
    "_failed",
}


def calculate_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()

    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)

    return sha.hexdigest()


def create_processing_log(source_file, stage, status, message=None):
    log = ProcessingLog(
        source_file_id=source_file.id,
        stage=stage,
        status=status,
        message=message,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.session.add(log)


def _safe_move(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / source.name

    if destination.exists():
        destination = destination_dir / f"{source.stem}_{uuid.uuid4().hex[:8]}{source.suffix}"

    shutil.move(str(source), str(destination))
    return destination


def _iter_ingest_files(ingest_root: Path):
    for path in ingest_root.rglob("*"):
        if not path.is_file():
            continue

        relative_parts = path.relative_to(ingest_root).parts

        if any(part in SYSTEM_FOLDER_NAMES for part in relative_parts):
            continue

        yield path


def scan_ingest_folder(uploaded_by_id=None, business_area=None, move_after_ingest=True):
    ingest_root = current_app.config["INGEST_ROOT"]
    storage_root = current_app.config["STORAGE_ROOT"]

    ingest_root.mkdir(parents=True, exist_ok=True)

    originals_dir = storage_root / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)

    processed_dir = ingest_root / "_processed"
    duplicates_dir = ingest_root / "_duplicates"
    rejected_dir = ingest_root / "_rejected"
    failed_dir = ingest_root / "_failed"

    results = {
        "ingested": 0,
        "duplicates": 0,
        "rejected": 0,
        "failed": 0,
        "scanned": 0,
        "items": [],
    }

    for source_path in list(_iter_ingest_files(ingest_root)):
        results["scanned"] += 1

        original_filename = source_path.name
        file_ext = source_path.suffix.lower()

        try:
            if file_ext not in ALLOWED_EXTENSIONS:
                results["rejected"] += 1
                if move_after_ingest:
                    moved_to = _safe_move(source_path, rejected_dir)
                else:
                    moved_to = source_path

                results["items"].append(
                    {
                        "filename": original_filename,
                        "status": "rejected",
                        "message": f"Unsupported file type: {file_ext}",
                        "moved_to": str(moved_to),
                    }
                )
                continue

            file_size = source_path.stat().st_size
            sha256_hash = calculate_sha256(source_path)

            existing = SourceFile.query.filter_by(
                sha256_hash=sha256_hash,
                file_size=file_size,
            ).first()

            if existing:
                results["duplicates"] += 1
                if move_after_ingest:
                    moved_to = _safe_move(source_path, duplicates_dir)
                else:
                    moved_to = source_path

                results["items"].append(
                    {
                        "filename": original_filename,
                        "status": "duplicate",
                        "message": f"Duplicate of SourceFile ID {existing.id}",
                        "moved_to": str(moved_to),
                    }
                )
                continue

            stored_filename = f"{uuid.uuid4().hex}{file_ext}"
            destination = originals_dir / stored_filename

            shutil.copy2(str(source_path), str(destination))

            mime_type, _ = mimetypes.guess_type(str(destination))

            source_file = SourceFile(
                original_filename=original_filename,
                stored_filename=stored_filename,
                file_ext=file_ext,
                mime_type=mime_type,
                file_size=file_size,
                sha256_hash=sha256_hash,
                storage_path=str(destination),
                source_type="folder_ingest",
                upload_method="folder_ingest",
                processing_status="uploaded",
                business_area=business_area or None,
                uploaded_by_id=uploaded_by_id,
            )

            db.session.add(source_file)
            db.session.flush()

            create_processing_log(
                source_file,
                stage="folder_ingest",
                status="success",
                message=f"File ingested from folder: {source_path}",
            )

            results["ingested"] += 1

            if move_after_ingest:
                moved_to = _safe_move(source_path, processed_dir)
            else:
                moved_to = source_path

            results["items"].append(
                {
                    "filename": original_filename,
                    "status": "ingested",
                    "message": f"Created SourceFile ID {source_file.id}",
                    "moved_to": str(moved_to),
                }
            )

        except Exception as exc:
            db.session.rollback()
            results["failed"] += 1

            try:
                if source_path.exists() and move_after_ingest:
                    moved_to = _safe_move(source_path, failed_dir)
                else:
                    moved_to = source_path
            except Exception:
                moved_to = source_path

            results["items"].append(
                {
                    "filename": original_filename,
                    "status": "failed",
                    "message": str(exc),
                    "moved_to": str(moved_to),
                }
            )

            continue

    db.session.commit()

    return results