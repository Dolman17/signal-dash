import hashlib
import mimetypes
import uuid
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
from wtforms import SelectField, TextAreaField, SubmitField
from wtforms.validators import Optional

from app.extensions import db
from app.models import SourceFile, ProcessingLog, utcnow

upload_bp = Blueprint("upload", __name__, url_prefix="/upload")


ALLOWED_EXTENSIONS = {
    ".eml",
    ".msg",
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".pptx",
    ".ppt",
    ".txt",
    ".md",
    ".html",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
}


BUSINESS_AREAS = [
    ("", "Auto-detect later"),
    ("Executive / Board", "Executive / Board"),
    ("Finance", "Finance"),
    ("Commercial", "Commercial"),
    ("Operations", "Operations"),
    ("Quality & Compliance", "Quality & Compliance"),
    ("HR / Workforce", "HR / Workforce"),
    ("Recruitment", "Recruitment"),
    ("IT / Systems", "IT / Systems"),
    ("Legal / Corporate", "Legal / Corporate"),
    ("Property / Estates", "Property / Estates"),
    ("Marketing / Brand", "Marketing / Brand"),
    ("PE Exit / Due Diligence", "PE Exit / Due Diligence"),
    ("Risk & Governance", "Risk & Governance"),
    ("Strategy", "Strategy"),
    ("M&A / Integration", "M&A / Integration"),
]


class UploadForm(FlaskForm):
    business_area = SelectField("Business area", choices=BUSINESS_AREAS, validators=[Optional()])
    notes = TextAreaField("Upload notes", validators=[Optional()])
    submit = SubmitField("Upload files")


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


@upload_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = UploadForm()

    if form.validate_on_submit():
        uploaded_files = request.files.getlist("files")

        if not uploaded_files or all(not f.filename for f in uploaded_files):
            flash("Choose at least one file to upload.", "error")
            return redirect(url_for("upload.index"))

        saved_count = 0
        duplicate_count = 0
        rejected_count = 0

        originals_dir = current_app.config["STORAGE_ROOT"] / "originals"
        originals_dir.mkdir(parents=True, exist_ok=True)

        for uploaded in uploaded_files:
            if not uploaded or not uploaded.filename:
                continue

            original_filename = uploaded.filename
            safe_name = secure_filename(original_filename)
            file_ext = Path(safe_name).suffix.lower()

            if file_ext not in ALLOWED_EXTENSIONS:
                rejected_count += 1
                continue

            stored_filename = f"{uuid.uuid4().hex}{file_ext}"
            destination = originals_dir / stored_filename

            uploaded.save(destination)

            file_size = destination.stat().st_size
            sha256_hash = calculate_sha256(destination)

            existing = SourceFile.query.filter_by(
                sha256_hash=sha256_hash,
                file_size=file_size,
            ).first()

            if existing:
                destination.unlink(missing_ok=True)
                duplicate_count += 1
                continue

            mime_type, _ = mimetypes.guess_type(str(destination))

            source_file = SourceFile(
                original_filename=original_filename,
                stored_filename=stored_filename,
                file_ext=file_ext,
                mime_type=mime_type,
                file_size=file_size,
                sha256_hash=sha256_hash,
                storage_path=str(destination),
                source_type="manual",
                upload_method="manual_upload",
                processing_status="uploaded",
                business_area=form.business_area.data or None,
                uploaded_by_id=current_user.id,
            )

            db.session.add(source_file)
            db.session.flush()

            create_processing_log(
                source_file,
                stage="upload",
                status="success",
                message="File uploaded and stored locally.",
            )

            saved_count += 1

        db.session.commit()

        if saved_count:
            flash(f"{saved_count} file(s) uploaded successfully.", "success")

        if duplicate_count:
            flash(f"{duplicate_count} duplicate file(s) skipped.", "info")

        if rejected_count:
            flash(f"{rejected_count} unsupported file type(s) rejected.", "error")

        return redirect(url_for("documents.index"))

    return render_template("upload/index.html", form=form, allowed_extensions=sorted(ALLOWED_EXTENSIONS))
