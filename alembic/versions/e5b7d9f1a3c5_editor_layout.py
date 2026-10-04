"""editor buttons a user hid from the post editor

Revision ID: e5b7d9f1a3c5
Revises: d3f5a7c9e1b3
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5b7d9f1a3c5'
down_revision: Union[str, None] = 'd3f5a7c9e1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('editor_hidden', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('users', 'editor_hidden')
