"""auto comment under published posts

Revision ID: b6d8f0a2c4e6
Revises: a1c3e5f7b9d2
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b6d8f0a2c4e6'
down_revision: Union[str, None] = 'a1c3e5f7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'auto_comment', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False, server_default='{}',
        ))


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('auto_comment')
