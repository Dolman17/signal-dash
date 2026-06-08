from pathlib import Path

from flask import Blueprint, render_template, abort, send_file, redirect, url_for, flash, request
from flask_login import login_required

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
from app.services.materialise import materialise_all_reviewed_documents, materialise_analysis_for_document
from app.services.queueing import enqueue_local_ai_review

documents_bp = Blueprint("documents", __name__, url_prefix="/documents")


DELETABLE_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}


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


def _is_deletable_attachment_noise(document):
    file_ext = (document.file_ext or "").lower()

    return (
        document.parent_file_id is not None
        or file_ext in DELETABLE_ATTACHMENT_EXTENSIONS
        or document.source_type in {"attachment", "email_attachment", "folder_attachment"}
    )


def _delete_file_if_safe(path_value):
    if not path_value:
        return

    try:
        path = Path(path_value)
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        # Disk cleanup should not block DB cleanup.
        pass


@documents_bp.route("/")
@login_required
def index():
    documents = SourceFile.query.order_by(SourceFile.created_at.desc()).all()
    return render_template("documents/index.html", documents=documents)


@documents_bp.route("/process-all", methods=["POST"])
@login_required
def process_all():
    documents = (
        SourceFile.query
        .filter(SourceFile.processing_status.in_(["uploaded", "failed"]))
        .order_by(SourceFile.created_at.asc())
        .all()
    )

    processed = 0
    failed = 0

    for document in documents:
        try:
            extract_source_file(document.id)
            processed += 1
        except Exception:
            failed += 1

    if processed:
        flash(f"{processed} document(s) processed.", "success")

    if failed:
        flash(f"{failed} document(s) failed. Check document detail logs.", "error")

    if not processed and not failed:
        flash("No uploaded or failed documents needed processing.", "info")

    return redirect(url_for("documents.index"))


@documents_bp.route("/materialise-all", methods=["POST"])
@login_required
def materialise_all():
    try:
        totals = materialise_all_reviewed_documents()

        flash(
            (
                f"Created records from {totals['documents']} reviewed document(s): "
                f"{totals['created_actions']} action(s), "
                f"{totals['created_risks']} risk(s), "
                f"{totals['created_insights']} insight(s). "
                f"Skipped {totals['skipped_actions'] + totals['skipped_risks'] + totals['skipped_insights']} duplicate/empty item(s)."
            ),
            "success",
        )

        if totals["failed"]:
            flash(f"{totals['failed']} document(s) failed while creating records.", "error")

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not create records from AI analysis: {exc}", "error")

    return redirect(url_for("documents.index"))


@documents_bp.route("/<int:document_id>")
@login_required
def detail(document_id):
    document = SourceFile.query.get_or_404(document_id)
    analysis = DocumentAnalysis.query.filter_by(source_file_id=document.id).first()
    can_delete_attachment_noise = _is_deletable_attachment_noise(document)

    return render_template(
        "documents/detail.html",
        document=document,
        analysis=analysis,
        can_delete_attachment_noise=can_delete_attachment_noise,
    )


@documents_bp.route("/<int:document_id>/download")
@login_required
def download(document_id):
    document = SourceFile.query.get_or_404(document_id)

    if not document.storage_path:
        abort(404)

    return send_file(
        document.storage_path,
        as_attachment=True,
        download_name=document.original_filename,
    )


@documents_bp.route("/<int:document_id>/process", methods=["POST"])
@login_required
def process(document_id):
    document = SourceFile.query.get_or_404(document_id)

    try:
        extract_source_file(document.id)
        flash("Document processed successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Document processing failed: {exc}", "error")

    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/<int:document_id>/local-ai-review", methods=["POST"])
@login_required
def local_ai_review(document_id):
    document = SourceFile.query.get_or_404(document_id)

    if not document.document_text or not document.document_text.text_preview:
        flash("Process/extract the document before running local AI review.", "error")
        return redirect(url_for("documents.detail", document_id=document.id))

    if document.processing_status in ["local_ai_queued", "local_ai_reviewing"]:
        flash("Local AI review is already queued or running.", "info")
        return redirect(url_for("documents.detail", document_id=document.id))

    try:
        job = enqueue_local_ai_review(document.id)

        document.processing_status = "local_ai_queued"
        document.processing_error = None

        _log(
            document.id,
            "local_ai_review",
            "queued",
            f"Queued local AI review job: {job.id}",
        )

        db.session.commit()

        flash("Local AI review queued. The worker will process it in the background.", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not queue local AI review: {exc}", "error")

    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/<int:document_id>/materialise", methods=["POST"])
@login_required
def materialise(document_id):
    document = SourceFile.query.get_or_404(document_id)

    try:
        result = materialise_analysis_for_document(document.id)

        flash(
            (
                f"Created {result['created_actions']} action(s), "
                f"{result['created_risks']} risk(s), "
                f"{result['created_insights']} insight(s). "
                f"Skipped {result['skipped_actions'] + result['skipped_risks'] + result['skipped_insights']} duplicate/empty item(s)."
            ),
            "success",
        )

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not create records from AI analysis: {exc}", "error")

    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/<int:document_id>/delete-attachment", methods=["POST"])
@login_required
def delete_attachment(document_id):
    document = SourceFile.query.get_or_404(document_id)

    if not _is_deletable_attachment_noise(document):
        flash("This delete action is only available for image/attachment noise files.", "error")
        return redirect(url_for("documents.detail", document_id=document.id))

    child_count = SourceFile.query.filter_by(parent_file_id=document.id).count()

    if child_count:
        flash("This file has child attachments and cannot be deleted with this quick-delete action.", "error")
        return redirect(url_for("documents.detail", document_id=document.id))

    original_filename = document.original_filename
    storage_path = document.storage_path

    extracted_text_path = None
    body_html_path = None

    if document.document_text and document.document_text.extracted_text_path:
        extracted_text_path = document.document_text.extracted_text_path

    if document.email_message and document.email_message.body_html_path:
        body_html_path = document.email_message.body_html_path

    try:
        # Remove AI/document records that have non-cascading foreign keys.
        DocumentAnalysis.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
        DocumentChunk.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
        AIProcessingRun.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)
        InsightEvidence.query.filter_by(source_file_id=document.id).delete(synchronize_session=False)

        # Preserve created business records but detach them from this noise file.
        ActionItem.query.filter_by(source_file_id=document.id).update(
            {"source_file_id": None},
            synchronize_session=False,
        )
        RiskFlag.query.filter_by(source_file_id=document.id).update(
            {"source_file_id": None},
            synchronize_session=False,
        )

        db.session.delete(document)
        db.session.commit()

        _delete_file_if_safe(storage_path)
        _delete_file_if_safe(extracted_text_path)
        _delete_file_if_safe(body_html_path)

        flash(f"Deleted attachment/noise file: {original_filename}", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not delete attachment/noise file: {exc}", "error")
        return redirect(url_for("documents.detail", document_id=document.id))

    next_url = request.form.get("next") or url_for("documents.index")
    return redirect(next_url)