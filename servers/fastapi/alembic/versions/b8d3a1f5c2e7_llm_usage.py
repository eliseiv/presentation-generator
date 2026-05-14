"""llm_usage_entries table

Revision ID: b8d3a1f5c2e7
Revises: a7c2f0d11a9b
Create Date: 2026-05-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b8d3a1f5c2e7'
down_revision: Union[str, None] = 'a7c2f0d11a9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_usage_entries" in inspector.get_table_names():
        return

    op.create_table(
        "llm_usage_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("presentation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=True),
        sa.Column("image_quality", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("audio_seconds", sa.Float(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_usage_entries_presentation_id",
        "llm_usage_entries",
        ["presentation_id"],
    )
    op.create_index(
        "ix_llm_usage_entries_user_id", "llm_usage_entries", ["user_id"]
    )
    op.create_index(
        "ix_llm_usage_entries_provider", "llm_usage_entries", ["provider"]
    )
    op.create_index("ix_llm_usage_entries_model", "llm_usage_entries", ["model"])
    op.create_index("ix_llm_usage_entries_kind", "llm_usage_entries", ["kind"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_usage_entries" not in inspector.get_table_names():
        return

    for ix in (
        "ix_llm_usage_entries_presentation_id",
        "ix_llm_usage_entries_user_id",
        "ix_llm_usage_entries_provider",
        "ix_llm_usage_entries_model",
        "ix_llm_usage_entries_kind",
    ):
        try:
            op.drop_index(ix, table_name="llm_usage_entries")
        except Exception:
            pass

    op.drop_table("llm_usage_entries")
