"""opt-in reminders that tomorrow has nothing scheduled

Revision ID: a1c3e5f7b9d2
Revises: c7e9b1d3f5a7
Create Date: 2026-09-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, None] = 'c7e9b1d3f5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        # Off for every existing channel: the owner switches it on from the channel's card.
        batch_op.add_column(sa.Column('gap_reminder', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('gap_reminded_on', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('gap_reminded_on')
        batch_op.drop_column('gap_reminder')
