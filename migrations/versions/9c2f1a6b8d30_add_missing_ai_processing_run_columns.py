"""add missing ai processing run columns

Revision ID: 9c2f1a6b8d30
Revises: 7f4c2d5e9a10
Create Date: 2026-06-09 08:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "9c2f1a6b8d30"
down_revision = "7f4c2d5e9a10"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(table_name, index_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    if not _column_exists("ai_processing_runs", "task_type"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("task_type", sa.String(length=120), nullable=False, server_default="local_ai_review"),
        )

    if not _column_exists("ai_processing_runs", "prompt_hash"):
        op.add_column("ai_processing_runs", sa.Column("prompt_hash", sa.String(length=64), nullable=True))

    if not _column_exists("ai_processing_runs", "input_token_estimate"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("input_token_estimate", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _column_exists("ai_processing_runs", "output_token_estimate"):
        op.add_column(
            "ai_processing_runs",
            sa.Column("output_token_estimate", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _column_exists("ai_processing_runs", "error_message"):
        op.add_column("ai_processing_runs", sa.Column("error_message", sa.Text(), nullable=True))

    if not _index_exists("ai_processing_runs", "ix_ai_processing_runs_status"):
        op.create_index(op.f("ix_ai_processing_runs_status"), "ai_processing_runs", ["status"], unique=False)

    op.alter_column("ai_processing_runs", "task_type", server_default=None)
    op.alter_column("ai_processing_runs", "input_token_estimate", server_default=None)
    op.alter_column("ai_processing_runs", "output_token_estimate", server_default=None)


def downgrade():
    if _index_exists("ai_processing_runs", "ix_ai_processing_runs_status"):
        op.drop_index(op.f("ix_ai_processing_runs_status"), table_name="ai_processing_runs")

    for column_name in [
        "error_message",
        "output_token_estimate",
        "input_token_estimate",
        "prompt_hash",
        "task_type",
    ]:
        if _column_exists("ai_processing_runs", column_name):
            op.drop_column("ai_processing_runs", column_name)
