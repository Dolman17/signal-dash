"""analysis table compatibility

Revision ID: c8d3a4f7b910
Revises: b4e2c9d1f650
Create Date: 2026-06-09 08:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d3a4f7b910"
down_revision = "b4e2c9d1f650"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in existing


def upgrade():
    if not _column_exists("document_analyses", "detailed_summary"):
        op.add_column("document_analyses", sa.Column("detailed_summary", sa.Text(), nullable=True))

    if not _column_exists("document_analyses", "key_points_json"):
        op.add_column("document_analyses", sa.Column("key_points_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "decisions_json"):
        op.add_column("document_analyses", sa.Column("decisions_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "actions_json"):
        op.add_column("document_analyses", sa.Column("actions_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "risks_json"):
        op.add_column("document_analyses", sa.Column("risks_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "opportunities_json"):
        op.add_column("document_analyses", sa.Column("opportunities_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "entities_json"):
        op.add_column("document_analyses", sa.Column("entities_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "due_diligence_json"):
        op.add_column("document_analyses", sa.Column("due_diligence_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "buyer_questions_json"):
        op.add_column("document_analyses", sa.Column("buyer_questions_json", sa.JSON(), nullable=True))

    if not _column_exists("document_analyses", "confidence_score"):
        op.add_column("document_analyses", sa.Column("confidence_score", sa.Float(), nullable=True))

    if not _column_exists("document_analyses", "evidence_strength"):
        op.add_column("document_analyses", sa.Column("evidence_strength", sa.String(length=80), nullable=True))

    if not _column_exists("document_analyses", "raw_response_path"):
        op.add_column("document_analyses", sa.Column("raw_response_path", sa.Text(), nullable=True))

    if not _column_exists("document_analyses", "created_at"):
        op.add_column("document_analyses", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE document_analyses SET created_at = NOW() WHERE created_at IS NULL")
        op.alter_column("document_analyses", "created_at", nullable=False)

    if not _column_exists("document_analyses", "updated_at"):
        op.add_column("document_analyses", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE document_analyses SET updated_at = NOW() WHERE updated_at IS NULL")
        op.alter_column("document_analyses", "updated_at", nullable=False)


def downgrade():
    for column_name in [
        "updated_at",
        "created_at",
        "raw_response_path",
        "evidence_strength",
        "confidence_score",
        "buyer_questions_json",
        "due_diligence_json",
        "entities_json",
        "opportunities_json",
        "risks_json",
        "actions_json",
        "decisions_json",
        "key_points_json",
        "detailed_summary",
    ]:
        if _column_exists("document_analyses", column_name):
            op.drop_column("document_analyses", column_name)
