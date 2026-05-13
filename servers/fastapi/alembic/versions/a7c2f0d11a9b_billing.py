"""billing: users, token ledger, presentation user_id+token_cost

Revision ID: a7c2f0d11a9b
Revises: 95b5127e93cd
Create Date: 2026-05-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a7c2f0d11a9b'
down_revision: Union[str, None] = 'c7b70d0f31b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "subscription",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "subscription_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "adapty_profile_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_users_adapty_profile_id", "users", ["adapty_profile_id"]
        )

    if "token_ledger_entries" not in existing_tables:
        op.create_table(
            "token_ledger_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("balance_after", sa.Integer(), nullable=False),
            sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "reference_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_token_ledger_entries_user_id",
            "token_ledger_entries",
            ["user_id"],
        )
        op.create_index(
            "ix_token_ledger_entries_reason",
            "token_ledger_entries",
            ["reason"],
        )
        op.create_index(
            "ix_token_ledger_entries_reference_id",
            "token_ledger_entries",
            ["reference_id"],
        )

    presentation_cols = {col["name"] for col in inspector.get_columns("presentations")}
    if "user_id" not in presentation_cols:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
                )
            )
        op.create_index("ix_presentations_user_id", "presentations", ["user_id"])
    if "token_cost" not in presentation_cols:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("token_cost", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "presentations" in existing_tables:
        presentation_cols = {
            col["name"] for col in inspector.get_columns("presentations")
        }
        if "token_cost" in presentation_cols:
            with op.batch_alter_table("presentations") as batch_op:
                batch_op.drop_column("token_cost")
        if "user_id" in presentation_cols:
            op.drop_index("ix_presentations_user_id", table_name="presentations")
            with op.batch_alter_table("presentations") as batch_op:
                batch_op.drop_column("user_id")

    if "token_ledger_entries" in existing_tables:
        op.drop_index(
            "ix_token_ledger_entries_reference_id",
            table_name="token_ledger_entries",
        )
        op.drop_index(
            "ix_token_ledger_entries_reason", table_name="token_ledger_entries"
        )
        op.drop_index(
            "ix_token_ledger_entries_user_id", table_name="token_ledger_entries"
        )
        op.drop_table("token_ledger_entries")

    if "users" in existing_tables:
        op.drop_index("ix_users_adapty_profile_id", table_name="users")
        op.drop_table("users")
