"""channel publish notify settings

Revision ID: b2f4a6c8d0e1
Revises: 79dcc01e2ad9
Create Date: 2026-09-14 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2f4a6c8d0e1'
down_revision: Union[str, None] = '79dcc01e2ad9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_published', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('notify_recipients', sa.String(length=16), nullable=False, server_default='owner'))


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('notify_recipients')
        batch_op.drop_column('notify_published')
