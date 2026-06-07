from flask import Blueprint, render_template, abort, send_file, redirect, url_for, flash
from flask_login import login_required

from app.extensions import db
from app.models import DocumentAnalysis, ProcessingLog, SourceFile, utcnow
from app.services.extraction import extract_source_file
from app.services.materialise import materialise_all_reviewed_documents, materialise_analysis_for_document
from app.services.queueing import enqueue_local_ai_review

documents_bp = Blueprint("documents", __name__, url_prefix="/documents")


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

    return render_template(
        "documents/detail.html",
        document=document,
        analysis=analysis,
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
