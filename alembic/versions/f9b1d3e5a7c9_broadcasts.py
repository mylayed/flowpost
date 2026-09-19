"""broadcasts: the owner's /broadcast, sent now or at a set time

Revision ID: f9b1d3e5a7c9
Revises: e3a5c7e9b1d3
Create Date: 2026-09-19 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f9b1d3e5a7c9'
down_revision: Union[str, None] = 'e3a5c7e9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table(
        'broadcasts',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('from_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('audience', sa.String(length=16), nullable=False),
        sa.Column('send_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('status_message_id', sa.Integer(), nullable=True),
        sa.Column('last_user_id', sa.BigInteger(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('sent', sa.Integer(), nullable=False),
        sa.Column('blocked', sa.Integer(), nullable=False),
        sa.Column('failed', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_broadcasts_send_at'), 'broadcasts', ['send_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_broadcasts_send_at'), table_name='broadcasts')
    op.drop_table('broadcasts')
