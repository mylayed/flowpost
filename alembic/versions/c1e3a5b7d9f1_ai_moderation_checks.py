"""starting AI moderation checks for channels connected before the «ai_mod» quota existed

Revision ID: c1e3a5b7d9f1
Revises: b6d8f0a2c4e6
Create Date: 2026-10-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1e3a5b7d9f1'
down_revision: Union[str, None] = 'b6d8f0a2c4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STARTING_CHECKS = 30  # the trial allowance of new channels


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO channel_quotas (channel_id, kind, remaining, updated_at) "
        "SELECT c.id, 'ai_mod', :n, CURRENT_TIMESTAMP FROM channels c "
        "WHERE NOT EXISTS (SELECT 1 FROM channel_quotas q WHERE q.channel_id = c.id AND q.kind = 'ai_mod')"
    ).bindparams(n=STARTING_CHECKS))


def downgrade() -> None:
    op.execute("DELETE FROM channel_quotas WHERE kind = 'ai_mod'")
