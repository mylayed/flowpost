"""wallet balance and ledger

Revision ID: c8e0a2b4d6f8
Revises: b3c5d7e9f1a3
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8e0a2b4d6f8'
down_revision: Union[str, None] = 'b3c5d7e9f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('balance', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('cashback', sa.Integer(), nullable=False, server_default='0'))
    op.create_table(
        'balance_ledger',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.String(length=16), nullable=False),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('ref', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_balance_ledger_user_id'), 'balance_ledger', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_balance_ledger_user_id'), table_name='balance_ledger')
    op.drop_table('balance_ledger')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('cashback')
        batch_op.drop_column('balance')
