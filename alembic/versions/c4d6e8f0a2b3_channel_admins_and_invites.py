"""channel admins and invites

Revision ID: c4d6e8f0a2b3
Revises: b2f4a6c8d0e1
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4d6e8f0a2b3'
down_revision: Union[str, None] = 'b2f4a6c8d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table(
        'channel_admins',
        sa.Column('id', BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', BIGINT_PK, nullable=False),
        sa.Column('user_id', BIGINT_PK, nullable=False),
        sa.Column('can_posts', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('can_settings', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('can_disconnect', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_channel_admins_channel_id_channels'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_channel_admins_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_channel_admins')),
        sa.UniqueConstraint('channel_id', 'user_id', name='uq_channel_admins_channel_user'),
    )
    with op.batch_alter_table('channel_admins', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_channel_admins_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_channel_admins_user_id'), ['user_id'], unique=False)

    op.create_table(
        'channel_invites',
        sa.Column('id', BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', BIGINT_PK, nullable=False),
        sa.Column('token', sa.String(length=32), nullable=False),
        sa.Column('can_posts', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('can_settings', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('can_disconnect', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_by', BIGINT_PK, nullable=False),
        sa.Column('used_by', BIGINT_PK, nullable=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_channel_invites_channel_id_channels'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_channel_invites_created_by_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['used_by'], ['users.id'], name=op.f('fk_channel_invites_used_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_channel_invites')),
        sa.UniqueConstraint('token', name='uq_channel_invites_token'),
    )
    with op.batch_alter_table('channel_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_channel_invites_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_channel_invites_token'), ['token'], unique=False)


def downgrade() -> None:
    op.drop_table('channel_invites')
    op.drop_table('channel_admins')
