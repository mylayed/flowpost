"""buttons a user saved to «Обране» to put under other posts

Revision ID: 5860be8615d6
Revises: ce1df64007df
Create Date: 2026-10-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5860be8615d6'
down_revision: Union[str, None] = 'ce1df64007df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('favorite_buttons', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('users', 'favorite_buttons')
