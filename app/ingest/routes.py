from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.services.folder_ingest import scan_ingest_folder

ingest_bp = Blueprint("ingest", __name__, url_prefix="/ingest")


@ingest_bp.route("/")
@login_required
def index():
    ingest_root = current_app.config["INGEST_ROOT"]
    ingest_root.mkdir(parents=True, exist_ok=True)

    pending_files = []

    for path in sorted(ingest_root.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(ingest_root)

        if relative.parts and relative.parts[0] in {
            "_processed",
            "_duplicates",
            "_rejected",
            "_failed",
        }:
            continue

        pending_files.append(
            {
                "name": path.name,
                "relative_path": str(relative),
                "size": path.stat().st_size,
                "suffix": path.suffix.lower(),
            }
        )

    return render_template(
        "ingest/index.html",
        ingest_root=ingest_root,
        pending_files=pending_files,
    )


@ingest_bp.route("/scan", methods=["POST"])
@login_required
def scan():
    result = scan_ingest_folder(
        uploaded_by_id=current_user.id,
        business_area=None,
        move_after_ingest=True,
    )

    if result["ingested"]:
        flash(f"{result['ingested']} file(s) ingested from folder.", "success")

    if result["duplicates"]:
        flash(f"{result['duplicates']} duplicate file(s) moved to _duplicates.", "info")

    if result["rejected"]:
        flash(f"{result['rejected']} unsupported file(s) moved to _rejected.", "error")

    if result["failed"]:
        flash(f"{result['failed']} file(s) failed and were moved to _failed.", "error")

    if not result["scanned"]:
        flash("No files found in the ingest folder.", "info")

    return redirect(url_for("ingest.index"))