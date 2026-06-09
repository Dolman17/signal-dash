"""relax legacy ai processing run columns

Revision ID: e1f6a9b2c430
Revises: c8d3a4f7b910
Create Date: 2026-06-09 08:55:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "e1f6a9b2c430"
down_revision = "c8d3a4f7b910"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in existing


def upgrade():
    if _column_exists("ai_processing_runs", "run_type"):
        op.alter_column("ai_processing_runs", "run_type", existing_type=sa.String(length=100), nullable=True)

    if _column_exists("ai_processing_runs", "prompt_version"):
        op.alter_column("ai_processing_runs", "prompt_version", existing_type=sa.String(length=100), nullable=True)

    if _column_exists("ai_processing_runs", "estimated_cost"):
        op.alter_column("ai_processing_runs", "estimated_cost", existing_type=sa.Numeric(precision=10, scale=4), nullable=True)


def downgrade():
    if _column_exists("ai_processing_runs", "run_type") and _column_exists("ai_processing_runs", "task_type"):
        op.execute("UPDATE ai_processing_runs SET run_type = task_type WHERE run_type IS NULL")
        op.alter_column("ai_processing_runs", "run_type", existing_type=sa.String(length=100), nullable=False)

    if _column_exists("ai_processing_runs", "prompt_version") and _column_exists("ai_processing_runs", "prompt_hash"):
        op.execute("UPDATE ai_processing_runs SET prompt_version = prompt_hash WHERE prompt_version IS NULL")
        op.alter_column("ai_processing_runs", "prompt_version", existing_type=sa.String(length=100), nullable=False)

    if _column_exists("ai_processing_runs", "estimated_cost"):
        op.execute("UPDATE ai_processing_runs SET estimated_cost = 0 WHERE estimated_cost IS NULL")
        op.alter_column("ai_processing_runs", "estimated_cost", existing_type=sa.Numeric(precision=10, scale=4), nullable=False)
