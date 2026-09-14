"""channel discussion group

Revision ID: d5e7f9a1b3c5
Revises: c4d6e8f0a2b3
Create Date: 2026-09-14 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5e7f9a1b3c5'
down_revision: Union[str, None] = 'c4d6e8f0a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discussion_chat_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('discussion_title', sa.String(length=256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('discussion_title')
        batch_op.drop_column('discussion_chat_id')
