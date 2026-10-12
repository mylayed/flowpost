"""giveaway auto-draw: a button giveaway's winners drawn and announced by the bot at a set time

Revision ID: b3bd4d9431c1
Revises: e8a0c2d4f6b8
Create Date: 2026-10-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3bd4d9431c1'
down_revision: Union[str, None] = 'e8a0c2d4f6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('giveaways', schema=None) as batch_op:
        batch_op.add_column(sa.Column('draw_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('draw_winners', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('draw_user_id', sa.BigInteger(), nullable=True))
        batch_op.create_index('ix_giveaways_draw_at', ['draw_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('giveaways', schema=None) as batch_op:
        batch_op.drop_index('ix_giveaways_draw_at')
        batch_op.drop_column('draw_user_id')
        batch_op.drop_column('draw_winners')
        batch_op.drop_column('draw_at')
