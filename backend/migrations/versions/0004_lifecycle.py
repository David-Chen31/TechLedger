"""Decision history, source staleness and durable run events.

Revision ID: 0004_lifecycle
Revises: 0003_research
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_lifecycle"
down_revision = "0003_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("decision_cards", sa.Column("stale_sources_json", sa.Text(), nullable=False, server_default="[]"))
    op.create_table("card_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("card_id", sa.String(36), sa.ForeignKey("decision_cards.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_card_events_card_id", "card_events", ["card_id"])
    op.create_table("run_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("research_runs.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_events_run_id")
    op.drop_table("run_events")
    op.drop_index("ix_card_events_card_id")
    op.drop_table("card_events")
    op.drop_column("decision_cards", "stale_sources_json")
