from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    source_files = db.relationship("SourceFile", back_populates="uploaded_by", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class LoginAudit(db.Model):
    __tablename__ = "login_audits"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    event_type = db.Column(db.String(80), nullable=False)
    ip_address = db.Column(db.String(80), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class SourceFile(db.Model):
    __tablename__ = "source_files"

    id = db.Column(db.Integer, primary_key=True)

    original_filename = db.Column(db.String(500), nullable=False)
    stored_filename = db.Column(db.String(500), nullable=False)
    file_ext = db.Column(db.String(40), nullable=True, index=True)
    mime_type = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    sha256_hash = db.Column(db.String(64), nullable=False, index=True)

    storage_path = db.Column(db.Text, nullable=False)

    source_type = db.Column(db.String(120), nullable=True)
    upload_method = db.Column(db.String(80), default="manual_upload", nullable=False)

    parent_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=True)

    processing_status = db.Column(db.String(80), default="uploaded", nullable=False, index=True)
    processing_error = db.Column(db.Text, nullable=True)

    document_category = db.Column(db.String(160), nullable=True, index=True)
    business_area = db.Column(db.String(160), nullable=True, index=True)
    sensitivity_level = db.Column(db.String(80), nullable=True)

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    uploaded_by = db.relationship("User", back_populates="source_files")
    parent_file = db.relationship("SourceFile", remote_side=[id], backref="child_files")

    document_text = db.relationship(
        "DocumentText",
        back_populates="source_file",
        uselist=False,
        cascade="all, delete-orphan",
    )

    email_message = db.relationship(
        "EmailMessage",
        back_populates="source_file",
        uselist=False,
        cascade="all, delete-orphan",
    )

    processing_logs = db.relationship(
        "ProcessingLog",
        back_populates="source_file",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="ProcessingLog.created_at.desc()",
    )

    due_diligence_evidence = db.relationship(
        "DueDiligenceEvidence",
        back_populates="source_file",
        cascade="all, delete-orphan",
        lazy=True,
    )

    __table_args__ = (
        db.UniqueConstraint("sha256_hash", "file_size", name="uq_source_file_hash_size"),
    )


class DocumentText(db.Model):
    __tablename__ = "document_texts"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    extracted_text_path = db.Column(db.Text, nullable=True)
    text_preview = db.Column(db.Text, nullable=True)
    word_count = db.Column(db.Integer, default=0, nullable=False)
    char_count = db.Column(db.Integer, default=0, nullable=False)

    extraction_method = db.Column(db.String(120), nullable=True)
    extraction_status = db.Column(db.String(80), default="pending", nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    source_file = db.relationship("SourceFile", back_populates="document_text")


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    chunk_index = db.Column(db.Integer, nullable=False)
    chunk_text = db.Column(db.Text, nullable=False)

    page_number = db.Column(db.Integer, nullable=True)
    sheet_name = db.Column(db.String(255), nullable=True)
    slide_number = db.Column(db.Integer, nullable=True)
    email_section = db.Column(db.String(120), nullable=True)
    token_estimate = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class ProcessingLog(db.Model):
    __tablename__ = "processing_logs"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    stage = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=True)

    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    source_file = db.relationship("SourceFile", back_populates="processing_logs")


class EmailMessage(db.Model):
    __tablename__ = "email_messages"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    message_id = db.Column(db.String(500), nullable=True, index=True)
    subject = db.Column(db.String(500), nullable=True)
    sender_name = db.Column(db.String(255), nullable=True)
    sender_email = db.Column(db.String(255), nullable=True, index=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    body_text = db.Column(db.Text, nullable=True)
    body_html_path = db.Column(db.Text, nullable=True)

    thread_key = db.Column(db.String(500), nullable=True, index=True)
    response_needed = db.Column(db.Boolean, default=False, nullable=False)
    urgency_level = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    source_file = db.relationship("SourceFile", back_populates="email_message")
    recipients = db.relationship(
        "EmailRecipient",
        back_populates="email_message",
        cascade="all, delete-orphan",
        lazy=True,
    )


class EmailRecipient(db.Model):
    __tablename__ = "email_recipients"

    id = db.Column(db.Integer, primary_key=True)
    email_message_id = db.Column(db.Integer, db.ForeignKey("email_messages.id"), nullable=False)

    recipient_type = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    email_message = db.relationship("EmailMessage", back_populates="recipients")


class AIProcessingRun(db.Model):
    __tablename__ = "ai_processing_runs"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    provider = db.Column(db.String(80), nullable=False)
    model_name = db.Column(db.String(160), nullable=False)
    task_type = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(80), default="queued", nullable=False, index=True)

    prompt_hash = db.Column(db.String(64), nullable=True)
    input_token_estimate = db.Column(db.Integer, default=0, nullable=False)
    output_token_estimate = db.Column(db.Integer, default=0, nullable=False)

    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class DocumentAnalysis(db.Model):
    __tablename__ = "document_analyses"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)

    provider = db.Column(db.String(80), nullable=False)
    model_name = db.Column(db.String(160), nullable=False)

    summary = db.Column(db.Text, nullable=True)
    detailed_summary = db.Column(db.Text, nullable=True)

    key_points_json = db.Column(db.JSON, nullable=True)
    decisions_json = db.Column(db.JSON, nullable=True)
    actions_json = db.Column(db.JSON, nullable=True)
    risks_json = db.Column(db.JSON, nullable=True)
    opportunities_json = db.Column(db.JSON, nullable=True)
    entities_json = db.Column(db.JSON, nullable=True)

    due_diligence_json = db.Column(db.JSON, nullable=True)
    buyer_questions_json = db.Column(db.JSON, nullable=True)

    confidence_score = db.Column(db.Float, nullable=True)
    evidence_strength = db.Column(db.String(80), nullable=True)

    raw_response_path = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class Insight(db.Model):
    __tablename__ = "insights"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(300), nullable=False)
    insight_type = db.Column(db.String(120), nullable=False, index=True)
    business_area = db.Column(db.String(160), nullable=True, index=True)
    category = db.Column(db.String(160), nullable=True, index=True)

    severity = db.Column(db.String(80), nullable=True, index=True)
    confidence = db.Column(db.String(80), nullable=True)

    summary = db.Column(db.Text, nullable=True)
    why_it_matters = db.Column(db.Text, nullable=True)
    buyer_relevance = db.Column(db.Text, nullable=True)
    suggested_action = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(80), default="open", nullable=False, index=True)
    owner = db.Column(db.String(255), nullable=True)

    first_seen_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    trend = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class InsightEvidence(db.Model):
    __tablename__ = "insight_evidence"

    id = db.Column(db.Integer, primary_key=True)

    insight_id = db.Column(db.Integer, db.ForeignKey("insights.id"), nullable=False)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)
    document_chunk_id = db.Column(db.Integer, db.ForeignKey("document_chunks.id"), nullable=True)

    evidence_snippet = db.Column(db.Text, nullable=True)

    page_number = db.Column(db.Integer, nullable=True)
    sheet_name = db.Column(db.String(255), nullable=True)
    slide_number = db.Column(db.Integer, nullable=True)
    email_section = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class ActionItem(db.Model):
    __tablename__ = "action_items"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    owner = db.Column(db.String(255), nullable=True)
    due_date = db.Column(db.Date, nullable=True)

    priority = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(80), default="open", nullable=False, index=True)
    business_area = db.Column(db.String(160), nullable=True, index=True)

    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=True)
    document_chunk_id = db.Column(db.Integer, db.ForeignKey("document_chunks.id"), nullable=True)
    related_insight_id = db.Column(db.Integer, db.ForeignKey("insights.id"), nullable=True)

    source_snippet = db.Column(db.Text, nullable=True)
    created_by_ai = db.Column(db.Boolean, default=False, nullable=False)
    confidence = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)


class RiskFlag(db.Model):
    __tablename__ = "risk_flags"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(300), nullable=False)
    risk_type = db.Column(db.String(160), nullable=True, index=True)
    business_area = db.Column(db.String(160), nullable=True, index=True)

    severity = db.Column(db.String(80), nullable=True, index=True)
    confidence = db.Column(db.String(80), nullable=True)
    likelihood = db.Column(db.String(80), nullable=True)
    impact = db.Column(db.String(80), nullable=True)
    valuation_impact = db.Column(db.String(80), nullable=True)

    buyer_relevance = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    mitigation = db.Column(db.Text, nullable=True)
    owner = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(80), default="open", nullable=False, index=True)

    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=True)
    related_insight_id = db.Column(db.Integer, db.ForeignKey("insights.id"), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class DueDiligenceEvidence(db.Model):
    __tablename__ = "due_diligence_evidence"

    id = db.Column(db.Integer, primary_key=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"), nullable=False)
    category_slug = db.Column(db.String(160), nullable=False, index=True)

    evidence_strength = db.Column(db.String(80), nullable=True, index=True)
    buyer_relevance = db.Column(db.String(80), nullable=True, index=True)

    is_pinned = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_excluded = db.Column(db.Boolean, default=False, nullable=False, index=True)

    management_note = db.Column(db.Text, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    source_file = db.relationship("SourceFile", back_populates="due_diligence_evidence")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    __table_args__ = (
        db.UniqueConstraint("source_file_id", "category_slug", name="uq_dd_evidence_source_category"),
    )


class DueDiligenceCategoryNote(db.Model):
    __tablename__ = "due_diligence_category_notes"

    id = db.Column(db.Integer, primary_key=True)
    category_slug = db.Column(db.String(160), unique=True, nullable=False, index=True)

    current_position = db.Column(db.Text, nullable=True)
    known_gaps = db.Column(db.Text, nullable=True)
    mitigating_actions = db.Column(db.Text, nullable=True)
    buyer_response_angle = db.Column(db.Text, nullable=True)

    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    updated_by = db.relationship("User")


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)

    key = db.Column(db.String(180), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    event_type = db.Column(db.String(120), nullable=False)
    object_type = db.Column(db.String(120), nullable=True)
    object_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class DailyBriefing(db.Model):
    __tablename__ = "daily_briefings"

    id = db.Column(db.Integer, primary_key=True)

    briefing_date = db.Column(db.Date, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)

    executive_summary = db.Column(db.Text, nullable=True)

    highlights_json = db.Column(db.JSON, nullable=True)
    risks_json = db.Column(db.JSON, nullable=True)
    opportunities_json = db.Column(db.JSON, nullable=True)
    actions_json = db.Column(db.JSON, nullable=True)
    exit_readiness_json = db.Column(db.JSON, nullable=True)

    source_file_ids_json = db.Column(db.JSON, nullable=True)

    provider = db.Column(db.String(80), nullable=True)
    model_name = db.Column(db.String(160), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint("briefing_date", name="uq_daily_briefing_date"),
    )
