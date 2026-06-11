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
from app.services.due_diligence_service import build_due_diligence_library
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
    ".ico",
    ".tif",
    ".tiff",
}

AI_COMPLETE_STATUSES = {
    "local_ai_complete",
    "records_created",
}

AI_BUSY_STATUSES = {
    "local_ai_queued",
    "local_ai_reviewing",
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


def _normalise_json_list(value, default_key="title"):
    if not value:
        return []

    if isinstance(value, dict):
        return [value]

    if not isinstance(value, list):
        value = [value]

    normalised = []
    for item in value:
        if isinstance(item, dict):
            normalised.append(item)
        elif item is None:
            continue
        else:
            text = str(item).strip()
            if text:
                normalised.append({default_key: text, "description": text})

    return normalised


def _normalise_analysis_for_template(analysis):
    if not analysis:
        return None

    analysis.key_points_json = _normalise_json_list(analysis.key_points_json, default_key="text")
    analysis.decisions_json = _normalise_json_list(analysis.decisions_json, default_key="decision")
    analysis.actions_json = _normalise_json_list(analysis.actions_json, default_key="title")
    analysis.risks_json = _normalise_json_list(analysis.risks_json, default_key="title")
    analysis.opportunities_json = _normalise_json_list(analysis.opportunities_json, default_key="title")
    analysis.entities_json = _normalise_json_list(analysis.entities_json, default_key="name")
    analysis.buyer_questions_json = _normalise_json_list(analysis.buyer_questions_json, default_key="question")

    if not isinstance(analysis.due_diligence_json, dict):
        analysis.due_diligence_json = {}

    if analysis.due_diligence_json:
        analysis.due_diligence_json["evidence_gaps"] = _normalise_json_list(
            analysis.due_diligence_json.get("evidence_gaps"),
            default_key="gap",
        )
        analysis.due_diligence_json["likely_buyer_questions"] = _normalise_json_list(
            analysis.due_diligence_json.get("likely_buyer_questions"),
            default_key="question",
        )
        analysis.due_diligence_json["recommended_follow_up"] = _normalise_json_list(
            analysis.due_diligence_json.get("recommended_follow_up"),
            default_key="title",
        )

    return analysis


def _is_deletable_attachment_noise(document):
    file_ext = (document.file_ext or "").lower()

    return (
        document.parent_file_id is not None
        or file_ext in DELETABLE_ATTACHMENT_EXTENSIONS
        or document.source_type in {"attachment", "email_attachment", "folder_attachment"}
    )


def _is_email_image_attachment(document):
    file_ext = (document.file_ext or "").lower()

    return (
        document.source_type == "email_attachment"
        and document.parent_file_id is not None
        and file_ext in DELETABLE_ATTACHMENT_EXTENSIONS
    )


def _is_ai_queue_candidate(document):
    if document.parent_file_id is not None:
        return False

    if _is_deletable_attachment_noise(document):
        return False

    if document.processing_status in AI_BUSY_STATUSES or document.processing_status in AI_COMPLETE_STATUSES:
        return False

    if document.processing_status not in {"extracted", "local_ai_failed"}:
        return False

    if not document.document_text or not document.document_text.text_preview:
        return False

    return True


def _due_diligence_categories_for_document(document_id):
    library = build_due_diligence_library()
    matched = []

    for category in library["categories"]:
        document_ids = {item.get("id") for item in category.get("documents", [])}
        analysis_source_ids = {item.get("source_file_id") for item in category.get("analyses", [])}
        risk_source_ids = {item.get("source_file_id") for item in category.get("risks", [])}
        action_source_ids = {item.get("source_file_id") for item in category.get("actions", [])}

        if document_id in document_ids or document_id in analysis_source_ids or document_id in risk_source_ids or document_id in action_source_ids:
            matched.append(category)

    return matched


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


def _delete_source_file_and_disk(document):
    original_filename = document.original_filename
    storage_path = document.storage_path

    extracted_text_path = None
    body_html_path = None

    if document.document_text and document.document_text.extracted_text_path:
        extracted_text_path = document.document_text.extracted_text_path

    if document.email_message and document.email_message.body_html_path:
        body_html_path = document.email_message.body_html_path

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
    db.session.flush()

    _delete_file_if_safe(storage_path)
    _delete_file_if_safe(extracted_text_path)
    _delete_file_if_safe(body_html_path)

    return original_filename


def _filter_options():
    def values_for(column):
        rows = (
            db.session.query(column)
            .filter(column.isnot(None))
            .distinct()
            .order_by(column.asc())
            .all()
        )
        return [row[0] for row in rows if row[0]]

    return {
        "statuses": values_for(SourceFile.processing_status),
        "file_types": values_for(SourceFile.file_ext),
        "business_areas": values_for(SourceFile.business_area),
        "source_types": values_for(SourceFile.source_type),
    }


def _apply_document_filters(query):
    status = request.args.get("status", "").strip()
    file_type = request.args.get("file_type", "").strip()
    business_area = request.args.get("business_area", "").strip()
    source_type = request.args.get("source_type", "").strip()
    attachment_filter = request.args.get("attachment_filter", "").strip()
    ai_filter = request.args.get("ai_filter", "").strip()

    if status:
        query = query.filter(SourceFile.processing_status == status)

    if file_type:
        query = query.filter(SourceFile.file_ext == file_type)

    if business_area:
        query = query.filter(SourceFile.business_area == business_area)

    if source_type:
        query = query.filter(SourceFile.source_type == source_type)

    if attachment_filter == "parents_only":
        query = query.filter(SourceFile.parent_file_id.is_(None))
    elif attachment_filter == "attachments_only":
        query = query.filter(SourceFile.parent_file_id.isnot(None))
    elif attachment_filter == "email_image_noise":
        query = query.filter(
            SourceFile.source_type == "email_attachment",
            SourceFile.parent_file_id.isnot(None),
            SourceFile.file_ext.in_(DELETABLE_ATTACHMENT_EXTENSIONS),
        )

    if ai_filter == "needs_ai":
        query = query.filter(SourceFile.processing_status.in_(["extracted", "local_ai_failed"]))
    elif ai_filter == "ai_busy":
        query = query.filter(SourceFile.processing_status.in_(AI_BUSY_STATUSES))
    elif ai_filter == "ai_complete":
        query = query.filter(SourceFile.processing_status.in_(AI_COMPLETE_STATUSES))
    elif ai_filter == "ai_failed":
        query = query.filter(SourceFile.processing_status == "local_ai_failed")

    return query


@documents_bp.route("/")
@login_required
def index():
    query = SourceFile.query
    query = _apply_document_filters(query)

    documents = query.order_by(SourceFile.created_at.desc()).limit(500).all()

    email_image_noise_count = (
        SourceFile.query
        .filter(
            SourceFile.source_type == "email_attachment",
            SourceFile.parent_file_id.isnot(None),
            SourceFile.file_ext.in_(DELETABLE_ATTACHMENT_EXTENSIONS),
        )
        .count()
    )

    ai_queue_candidate_count = sum(1 for document in documents if _is_ai_queue_candidate(document))

    return render_template(
        "documents/index.html",
        documents=documents,
        filter_options=_filter_options(),
        active_filters=request.args,
        email_image_noise_count=email_image_noise_count,
        ai_queue_candidate_count=ai_queue_candidate_count,
    )


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


@documents_bp.route("/queue-ai-extracted", methods=["POST"])
@login_required
def queue_ai_extracted():
    try:
        limit = int(request.form.get("limit", 10))
    except Exception:
        limit = 10

    limit = max(1, min(limit, 50))

    documents = (
        SourceFile.query
        .filter(SourceFile.processing_status.in_(["extracted", "local_ai_failed"]))
        .filter(SourceFile.parent_file_id.is_(None))
        .order_by(SourceFile.created_at.asc())
        .limit(200)
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
                f"Queued local AI review job from bulk action: {job.id}",
            )

            queued += 1
        except Exception as exc:
            failed += 1
            _log(
                document.id,
                "local_ai_review",
                "failed",
                f"Bulk queue failed: {exc}",
            )
    db.session.commit()

    if queued:
        flash(f"Queued {queued} extracted document(s) for local AI review.", "success")

    if skipped:
        flash(f"Skipped {skipped} document(s) that were not eligible for AI review.", "info")

    if failed:
        flash(f"{failed} document(s) could not be queued.", "error")

    if not queued and not skipped and not failed:
        flash("No extracted documents were eligible for local AI review.", "info")

    return redirect(url_for("documents.index"))


@documents_bp.route("/cleanup-email-images", methods=["POST"])
@login_required
def cleanup_email_images():
    documents = (
        SourceFile.query
        .filter(
            SourceFile.source_type == "email_attachment",
            SourceFile.parent_file_id.isnot(None),
            SourceFile.file_ext.in_(DELETABLE_ATTACHMENT_EXTENSIONS),
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

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(f"Email image cleanup failed: {exc}", "error")
        return redirect(url_for("documents.index"))

    if deleted:
        flash(f"Deleted {deleted} embedded email image attachment(s).", "success")

    if failed:
        flash(f"{failed} email image attachment(s) could not be deleted.", "error")

    if not deleted and not failed:
        flash("No embedded email image attachments found to delete.", "info")

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
    analysis = _normalise_analysis_for_template(analysis)
    can_delete_attachment_noise = _is_deletable_attachment_noise(document)
    due_diligence_categories = _due_diligence_categories_for_document(document.id)

    return render_template(
        "documents/detail.html",
        document=document,
        analysis=analysis,
        can_delete_attachment_noise=can_delete_attachment_noise,
        due_diligence_categories=due_diligence_categories,
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

    try:
        _delete_source_file_and_disk(document)
        db.session.commit()

        flash(f"Deleted attachment/noise file: {original_filename}", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not delete attachment/noise file: {exc}", "error")
        return redirect(url_for("documents.detail", document_id=document.id))

    next_url = request.form.get("next") or url_for("documents.index")
    return redirect(next_url)
