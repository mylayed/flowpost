"""post part poll

Revision ID: da7a23abe61e
Revises: f7a9c1d3e5b7
Create Date: 2026-09-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'da7a23abe61e'
down_revision: Union[str, None] = 'a1c3e5f7b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('post_parts', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'poll', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table('post_parts', schema=None) as batch_op:
        batch_op.drop_column('poll')
