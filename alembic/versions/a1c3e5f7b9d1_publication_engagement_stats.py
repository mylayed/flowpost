"""publication engagement stats

Revision ID: a1c3e5f7b9d1
Revises: f7a9c1d3e5b7
Create Date: 2026-09-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1c3e5f7b9d1'
down_revision: Union[str, None] = 'f7a9c1d3e5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('publications', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'reactions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False, server_default='{}',
        ))
        batch_op.add_column(sa.Column('comments_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('discussion_thread_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('publications', schema=None) as batch_op:
        batch_op.drop_column('discussion_thread_id')
        batch_op.drop_column('comments_count')
        batch_op.drop_column('reactions')
