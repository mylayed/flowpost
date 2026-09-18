"""support thread activity

Revision ID: d1f3b5c7e9a1
Revises: c9e1a3b5d7f9
Create Date: 2026-09-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1f3b5c7e9a1'
down_revision: Union[str, None] = 'c9e1a3b5d7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('support_threads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_user_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('support_threads', schema=None) as batch_op:
        batch_op.drop_column('last_reply_at')
        batch_op.drop_column('last_user_at')
