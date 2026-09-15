"""per-channel trial

Revision ID: f2b4d6e8a0c2
Revises: e1a3c5d7f9b1
Create Date: 2026-09-15 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f2b4d6e8a0c2'
down_revision: Union[str, None] = 'e1a3c5d7f9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True))
    # Channels connected before per-channel trials keep their owner's existing account trial.
    op.execute(
        "UPDATE channels SET trial_ends_at = (SELECT users.trial_ends_at FROM users WHERE users.id = channels.owner_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('trial_ends_at')
