"""add due diligence curation

Revision ID: 7f4c2d5e9a10
Revises: dbbd111d0b76
Create Date: 2026-06-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "7f4c2d5e9a10"
down_revision = "dbbd111d0b76"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "due_diligence_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("category_slug", sa.String(length=160), nullable=False),
        sa.Column("evidence_strength", sa.String(length=80), nullable=True),
        sa.Column("buyer_relevance", sa.String(length=80), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("management_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_id", "category_slug", name="uq_dd_evidence_source_category"),
    )
    op.create_index(op.f("ix_due_diligence_evidence_buyer_relevance"), "due_diligence_evidence", ["buyer_relevance"], unique=False)
    op.create_index(op.f("ix_due_diligence_evidence_category_slug"), "due_diligence_evidence", ["category_slug"], unique=False)
    op.create_index(op.f("ix_due_diligence_evidence_evidence_strength"), "due_diligence_evidence", ["evidence_strength"], unique=False)
    op.create_index(op.f("ix_due_diligence_evidence_is_excluded"), "due_diligence_evidence", ["is_excluded"], unique=False)
    op.create_index(op.f("ix_due_diligence_evidence_is_pinned"), "due_diligence_evidence", ["is_pinned"], unique=False)

    op.create_table(
        "due_diligence_category_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_slug", sa.String(length=160), nullable=False),
        sa.Column("current_position", sa.Text(), nullable=True),
        sa.Column("known_gaps", sa.Text(), nullable=True),
        sa.Column("mitigating_actions", sa.Text(), nullable=True),
        sa.Column("buyer_response_angle", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_slug"),
    )
    op.create_index(op.f("ix_due_diligence_category_notes_category_slug"), "due_diligence_category_notes", ["category_slug"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_due_diligence_category_notes_category_slug"), table_name="due_diligence_category_notes")
    op.drop_table("due_diligence_category_notes")

    op.drop_index(op.f("ix_due_diligence_evidence_is_pinned"), table_name="due_diligence_evidence")
    op.drop_index(op.f("ix_due_diligence_evidence_is_excluded"), table_name="due_diligence_evidence")
    op.drop_index(op.f("ix_due_diligence_evidence_evidence_strength"), table_name="due_diligence_evidence")
    op.drop_index(op.f("ix_due_diligence_evidence_category_slug"), table_name="due_diligence_evidence")
    op.drop_index(op.f("ix_due_diligence_evidence_buyer_relevance"), table_name="due_diligence_evidence")
    op.drop_table("due_diligence_evidence")
