"""post part source signature

Revision ID: f7a9c1d3e5b7
Revises: e6f8a0b2c4d6
Create Date: 2026-09-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7a9c1d3e5b7'
down_revision: Union[str, None] = 'e6f8a0b2c4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('post_parts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_signature', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('post_parts', schema=None) as batch_op:
        batch_op.drop_column('source_signature')
