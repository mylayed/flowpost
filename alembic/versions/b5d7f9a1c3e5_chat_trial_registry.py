"""one trial per chat, kept across reconnections

Revision ID: b5d7f9a1c3e5
Revises: a2c4e6f8b0d2
Create Date: 2026-09-21 12:00:00.000000

"""
import json
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b5d7f9a1c3e5'
down_revision: Union[str, None] = 'a2c4e6f8b0d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_trials',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('posts_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_owner_id', sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_trials_chat_id'), 'chat_trials', ['chat_id'], unique=True)

    # Chats connected right now keep the trial they are already on (the longest one, if the same chat is
    # connected from several accounts) — nobody's running trial gets cut short by this migration.
    op.execute(
        "INSERT INTO chat_trials (chat_id, started_at, trial_ends_at, posts_used, first_owner_id) "
        "SELECT chat_id, MIN(created_at), MAX(trial_ends_at), 0, MIN(owner_id) "
        "FROM channels WHERE trial_ends_at IS NOT NULL GROUP BY chat_id"
    )

    # Chats disconnected earlier: their trial was remembered in a `channel_deleted` usage event. Without
    # a record of when it started, assume the 30 days the trial has always been.
    bind = op.get_bind()
    known = {row[0] for row in bind.execute(sa.text("SELECT chat_id FROM chat_trials"))}
    seen: dict[int, tuple] = {}
    for user_id, meta in bind.execute(sa.text("SELECT user_id, meta FROM usage_events WHERE kind = 'channel_deleted'")):
        meta = json.loads(meta) if isinstance(meta, (str, bytes)) else (meta or {})
        chat_id, ends_at = meta.get("chat_id"), meta.get("trial_ends_at")
        if chat_id is None or ends_at is None or chat_id in known:
            continue
        ends_at = datetime.fromisoformat(ends_at)
        ends_at = (ends_at if ends_at.tzinfo else ends_at.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        if bind.dialect.name == 'sqlite':
            ends_at = ends_at.replace(tzinfo=None)
        if chat_id not in seen or ends_at > seen[chat_id][1]:
            seen[chat_id] = (user_id, ends_at)
    for chat_id, (user_id, ends_at) in seen.items():
        bind.execute(
            sa.text("INSERT INTO chat_trials (chat_id, started_at, trial_ends_at, posts_used, first_owner_id) "
                    "VALUES (:chat_id, :started_at, :ends_at, 0, :user_id)"),
            {"chat_id": chat_id, "started_at": ends_at - timedelta(days=30), "ends_at": ends_at, "user_id": user_id},
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_trials_chat_id'), table_name='chat_trials')
    op.drop_table('chat_trials')
