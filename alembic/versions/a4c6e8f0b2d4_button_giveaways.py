"""giveaways with their own «Беру участь» button under a post, and who tapped it

Revision ID: a4c6e8f0b2d4
Revises: 4e6a8c0b2d1f
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4c6e8f0b2d4'
down_revision: Union[str, None] = '4e6a8c0b2d1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table(
        'giveaways',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', PK, nullable=False),
        sa.Column('post_id', PK, nullable=True),
        sa.Column('button_text', sa.String(length=64), nullable=False),
        sa.Column('subscribers_only', sa.Boolean(), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False),
        sa.Column('entries', sa.Integer(), nullable=False),
        sa.Column('shown', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_giveaways_channel_id'), 'giveaways', ['channel_id'], unique=False)
    op.create_index(op.f('ix_giveaways_post_id'), 'giveaways', ['post_id'], unique=False)
    op.create_table(
        'giveaway_entries',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('giveaway_id', PK, nullable=False),
        sa.Column('user_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('giveaway_id', 'user_tg_id', name='uq_giveaway_entries_giveaway_user'),
    )
    op.create_index(op.f('ix_giveaway_entries_giveaway_id'), 'giveaway_entries', ['giveaway_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_giveaway_entries_giveaway_id'), table_name='giveaway_entries')
    op.drop_table('giveaway_entries')
    op.drop_index(op.f('ix_giveaways_post_id'), table_name='giveaways')
    op.drop_index(op.f('ix_giveaways_channel_id'), table_name='giveaways')
    op.drop_table('giveaways')
