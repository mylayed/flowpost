"""folder icon and style

Revision ID: b4d6f8a0c2e4
Revises: a3c5e7f9b1d3
Create Date: 2026-09-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4d6f8a0c2e4'
down_revision: Union[str, None] = 'a3c5e7f9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('channel_folders', sa.Column('icon', sa.String(length=16), nullable=False, server_default='🗂'))
    op.add_column('channel_folders', sa.Column('style', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('channel_folders', 'style')
    op.drop_column('channel_folders', 'icon')
