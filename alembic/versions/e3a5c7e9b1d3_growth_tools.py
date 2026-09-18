"""growth tools: tracked invite links, join requests, RSS feeds, member counts, translation, weekly report;
support threads remember whether they await a reply

Revision ID: e3a5c7e9b1d3
Revises: d1f3b5c7e9a1
Create Date: 2026-09-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e3a5c7e9b1d3'
down_revision: Union[str, None] = 'd1f3b5c7e9a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    with op.batch_alter_table('support_threads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('awaiting', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        "UPDATE support_threads SET awaiting = (last_user_at IS NOT NULL "
        "AND (last_reply_at IS NULL OR last_reply_at < last_user_at))"
    )

    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('join_settings', JSON, nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('translate_lang', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('weekly_report', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('report_sent_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'invite_links',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=32), nullable=False),
        sa.Column('url', sa.String(length=128), nullable=False),
        sa.Column('cost', sa.Float(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invite_links_channel_id'), 'invite_links', ['channel_id'], unique=False)
    op.create_index(op.f('ix_invite_links_url'), 'invite_links', ['url'], unique=False)

    op.create_table(
        'invite_joins',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('link_id', sa.Integer(), nullable=False),
        sa.Column('user_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['link_id'], ['invite_links.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('link_id', 'user_tg_id', name='uq_invite_joins_link_user'),
    )
    op.create_index(op.f('ix_invite_joins_link_id'), 'invite_joins', ['link_id'], unique=False)

    op.create_table(
        'join_requests',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('user_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('invite_url', sa.String(length=128), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approve_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'user_tg_id', name='uq_join_requests_channel_user'),
    )
    op.create_index(op.f('ix_join_requests_channel_id'), 'join_requests', ['channel_id'], unique=False)
    op.create_index(op.f('ix_join_requests_approve_at'), 'join_requests', ['approve_at'], unique=False)

    op.create_table(
        'feeds',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('mode', sa.String(length=8), nullable=False),
        sa.Column('rewrite', sa.Boolean(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('seen', JSON, nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_feeds_channel_id'), 'feeds', ['channel_id'], unique=False)

    op.create_table(
        'channel_member_counts',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'day', name='uq_channel_member_counts_channel_day'),
    )
    op.create_index(op.f('ix_channel_member_counts_channel_id'), 'channel_member_counts', ['channel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_member_counts_channel_id'), table_name='channel_member_counts')
    op.drop_table('channel_member_counts')
    op.drop_index(op.f('ix_feeds_channel_id'), table_name='feeds')
    op.drop_table('feeds')
    op.drop_index(op.f('ix_join_requests_approve_at'), table_name='join_requests')
    op.drop_index(op.f('ix_join_requests_channel_id'), table_name='join_requests')
    op.drop_table('join_requests')
    op.drop_index(op.f('ix_invite_joins_link_id'), table_name='invite_joins')
    op.drop_table('invite_joins')
    op.drop_index(op.f('ix_invite_links_url'), table_name='invite_links')
    op.drop_index(op.f('ix_invite_links_channel_id'), table_name='invite_links')
    op.drop_table('invite_links')
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('report_sent_at')
        batch_op.drop_column('weekly_report')
        batch_op.drop_column('translate_lang')
        batch_op.drop_column('join_settings')
    with op.batch_alter_table('support_threads', schema=None) as batch_op:
        batch_op.drop_column('awaiting')
