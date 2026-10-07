"""extra auto-signature templates per channel, picked in the post editor

Revision ID: b3d5f7a9c1e3
Revises: 5860be8615d6
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3d5f7a9c1e3'
down_revision: Union[str, None] = '5860be8615d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('channels', sa.Column('signature_extra', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('channels', 'signature_extra')
