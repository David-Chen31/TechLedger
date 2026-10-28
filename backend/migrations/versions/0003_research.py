"""Research runs and reviewable decision cards.

Revision ID: 0003_research
Revises: 0002_index
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_research"
down_revision = "0002_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("research_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.Column("candidates", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_table("decision_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("research_runs.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("review_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_table("decision_cards")
    op.drop_table("research_runs")
