"""channel quotas

Revision ID: d9f1b3c5e7a9
Revises: c8e0a2b4d6f8
Create Date: 2026-09-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9f1b3c5e7a9'
down_revision: Union[str, None] = 'c8e0a2b4d6f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'channel_quotas',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('remaining', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'kind', name='uq_channel_quotas_channel_kind'),
    )
    op.create_index(op.f('ix_channel_quotas_channel_id'), 'channel_quotas', ['channel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_quotas_channel_id'), table_name='channel_quotas')
    op.drop_table('channel_quotas')
