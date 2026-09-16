"""channel folders

Revision ID: a3c5e7f9b1d3
Revises: f2b4d6e8a0c2
Create Date: 2026-09-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3c5e7f9b1d3'
down_revision: Union[str, None] = 'f2b4d6e8a0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'channel_folders',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_channel_folders_owner_id'), 'channel_folders', ['owner_id'], unique=False)
    op.create_table(
        'channel_folder_items',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('folder_id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['folder_id'], ['channel_folders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('folder_id', 'channel_id', name='uq_channel_folder_items_folder_channel'),
    )
    op.create_index(op.f('ix_channel_folder_items_folder_id'), 'channel_folder_items', ['folder_id'], unique=False)
    op.create_index(op.f('ix_channel_folder_items_channel_id'), 'channel_folder_items', ['channel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_folder_items_channel_id'), table_name='channel_folder_items')
    op.drop_index(op.f('ix_channel_folder_items_folder_id'), table_name='channel_folder_items')
    op.drop_table('channel_folder_items')
    op.drop_index(op.f('ix_channel_folders_owner_id'), table_name='channel_folders')
    op.drop_table('channel_folders')
