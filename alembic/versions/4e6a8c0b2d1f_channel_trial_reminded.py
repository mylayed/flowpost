"""trial starts with the channel: per-channel reminder, account trials of owners without channels taken back

Revision ID: 4e6a8c0b2d1f
Revises: e5b7d9f1a3c5
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from flowpost.db.types import UTCDateTime, utcnow

# revision identifiers, used by Alembic.
revision: str = '4e6a8c0b2d1f'
down_revision: Union[str, None] = 'e5b7d9f1a3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

users = sa.table("users", sa.column("id", sa.Integer), sa.column("trial_ends_at", UTCDateTime))
channels = sa.table("channels", sa.column("owner_id", sa.Integer))
chat_trials = sa.table("chat_trials", sa.column("first_owner_id", sa.Integer))


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trial_reminded', sa.Boolean(), server_default=sa.false(), nullable=False))
    # A channel still on the trial it inherited from its owner's account was already covered by that reminder.
    op.execute(
        "UPDATE channels SET trial_reminded = TRUE WHERE EXISTS (SELECT 1 FROM users WHERE users.id = channels.owner_id"
        " AND users.trial_reminded AND users.trial_ends_at = channels.trial_ends_at)"
    )

    # Owners who have never connected a chat lose the account trial /start gave them: their trial now starts
    # when they connect their first channel.
    now = utcnow()
    op.get_bind().execute(
        sa.update(users)
        .where(
            users.c.trial_ends_at > now,
            ~sa.exists().where(channels.c.owner_id == users.c.id),
            ~sa.exists().where(chat_trials.c.first_owner_id == users.c.id),
        )
        .values(trial_ends_at=now)
    )


def downgrade() -> None:
    # Account trials taken back are not handed out again.
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('trial_reminded')
