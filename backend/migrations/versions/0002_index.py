"""Add reviewed source indexing and stable text ranges.

Revision ID: 0002_index
Revises: 0001_sources
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_index"
down_revision = "0001_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "indexed_documents",
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("source_snapshots.id"), primary_key=True),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_chunk_snapshot_ordinal"),
    )
    op.create_index("ix_chunks_snapshot_id", "chunks", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_snapshot_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("indexed_documents")
    op.drop_column("sources", "reviewed_at")
    op.drop_column("sources", "review_note")
