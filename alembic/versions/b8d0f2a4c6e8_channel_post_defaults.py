"""channel post defaults

Revision ID: b8d0f2a4c6e8
Revises: a7c9e1f3b5d7
Create Date: 2026-09-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8d0f2a4c6e8'
down_revision: Union[str, None] = 'a7c9e1f3b5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'post_defaults', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False, server_default='{}',
        ))


def downgrade() -> None:
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_column('post_defaults')
