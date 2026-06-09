"""ai run timestamp columns

Revision ID: b4e2c9d1f650
Revises: 9c2f1a6b8d30
Create Date: 2026-06-09 08:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "b4e2c9d1f650"
down_revision = "9c2f1a6b8d30"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in existing


def upgrade():
    if not _column_exists("ai_processing_runs", "started_at"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists("ai_processing_runs", "completed_at"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists("ai_processing_runs", "created_at"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute("UPDATE ai_processing_runs SET created_at = NOW() WHERE created_at IS NULL")
        op.alter_column("ai_processing_runs", "created_at", nullable=False)

    if not _column_exists("ai_processing_runs", "updated_at"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute("UPDATE ai_processing_runs SET updated_at = NOW() WHERE updated_at IS NULL")
        op.alter_column("ai_processing_runs", "updated_at", nullable=False)


def downgrade():
    for column_name in ["updated_at", "created_at", "completed_at", "started_at"]:
        if _column_exists("ai_processing_runs", column_name):
            op.drop_column("ai_processing_runs", column_name)
