"""longer trial: 30 days, 100 posts, 15 watermarks per kind and 15 AI texts

Revision ID: a7c9e1f3b5d7
Revises: c5e7a9b1d3f5
Create Date: 2026-09-17 09:00:00.000000

"""
from datetime import timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from flowpost.db.types import UTCDateTime, utcnow

# revision identifiers, used by Alembic.
revision: str = 'a7c9e1f3b5d7'
down_revision: Union[str, None] = 'c5e7a9b1d3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The new trial terms reach channels and accounts whose trial is still running; expired trials stay expired.
TRIAL_DAYS = 30
QUOTA_TOP_UP = {"wm_photo": 10, "wm_video": 10, "ai_text": 10}  # 5 → 15 granted on connection

channels = sa.table(
    "channels", sa.column("id", sa.Integer), sa.column("created_at", UTCDateTime), sa.column("trial_ends_at", UTCDateTime),
)
users = sa.table(
    "users", sa.column("id", sa.Integer), sa.column("created_at", UTCDateTime), sa.column("trial_ends_at", UTCDateTime),
    sa.column("trial_reminded", sa.Boolean),
)
quotas = sa.table(
    "channel_quotas", sa.column("id", sa.Integer), sa.column("channel_id", sa.Integer), sa.column("kind", sa.String),
    sa.column("remaining", sa.Integer), sa.column("updated_at", UTCDateTime),
)


def upgrade() -> None:
    conn = op.get_bind()
    now = utcnow()

    active = conn.execute(
        sa.select(channels.c.id, channels.c.created_at, channels.c.trial_ends_at).where(channels.c.trial_ends_at > now)
    ).all()
    for channel_id, created_at, ends_at in active:
        new_end = created_at + timedelta(days=TRIAL_DAYS)
        if new_end > ends_at:
            conn.execute(sa.update(channels).where(channels.c.id == channel_id).values(trial_ends_at=new_end))
        for kind, amount in QUOTA_TOP_UP.items():
            row = conn.execute(
                sa.select(quotas.c.id).where(quotas.c.channel_id == channel_id, quotas.c.kind == kind)
            ).first()
            if row is None:
                conn.execute(sa.insert(quotas).values(channel_id=channel_id, kind=kind, remaining=amount, updated_at=now))
            else:
                conn.execute(
                    sa.update(quotas).where(quotas.c.id == row.id)
                    .values(remaining=quotas.c.remaining + amount, updated_at=now)
                )

    for user_id, created_at, ends_at in conn.execute(
        sa.select(users.c.id, users.c.created_at, users.c.trial_ends_at).where(users.c.trial_ends_at > now)
    ).all():
        new_end = created_at + timedelta(days=TRIAL_DAYS)
        if new_end > ends_at:
            # The "trial ends within a day" reminder may already have gone out for the old end date.
            conn.execute(
                sa.update(users).where(users.c.id == user_id).values(trial_ends_at=new_end, trial_reminded=False)
            )


def downgrade() -> None:
    # Extended trials and granted quotas are not taken back.
    pass
