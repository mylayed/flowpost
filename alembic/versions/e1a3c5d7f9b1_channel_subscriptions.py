"""channel subscriptions

Revision ID: e1a3c5d7f9b1
Revises: d9f1b3c5e7a9
Create Date: 2026-09-15 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e1a3c5d7f9b1'
down_revision: Union[str, None] = 'd9f1b3c5e7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'channel_subscriptions',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('posts_per_day', sa.Integer(), nullable=False),
        sa.Column('paid_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', name='uq_channel_subscriptions_channel_id'),
    )


def downgrade() -> None:
    op.drop_table('channel_subscriptions')
