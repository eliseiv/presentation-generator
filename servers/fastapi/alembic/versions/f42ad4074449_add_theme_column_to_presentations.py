"""add theme column to presentations

Revision ID: f42ad4074449
Revises: 00b3c27a13bc
Create Date: 2026-03-24 12:42:32.369006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f42ad4074449'
down_revision: Union[str, None] = '00b3c27a13bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "theme" in columns:
        return

    op.add_column('presentations', sa.Column('theme', sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "theme" not in columns:
        return

    op.drop_column('presentations', 'theme')
