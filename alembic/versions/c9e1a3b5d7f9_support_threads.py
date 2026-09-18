"""support threads

Revision ID: c9e1a3b5d7f9
Revises: b8d0f2a4c6e8
Create Date: 2026-09-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9e1a3b5d7f9'
down_revision: Union[str, None] = 'b8d0f2a4c6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_threads',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_id', 'user_id', name='uq_support_threads_chat_user'),
    )
    op.create_index(op.f('ix_support_threads_user_id'), 'support_threads', ['user_id'], unique=False)
    op.create_index('ix_support_threads_chat_topic', 'support_threads', ['chat_id', 'topic_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_support_threads_chat_topic', table_name='support_threads')
    op.drop_index(op.f('ix_support_threads_user_id'), table_name='support_threads')
    op.drop_table('support_threads')
