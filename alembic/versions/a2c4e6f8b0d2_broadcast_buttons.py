"""broadcast buttons: link buttons and the add-channel button under a /broadcast

Revision ID: a2c4e6f8b0d2
Revises: f9b1d3e5a7c9
Create Date: 2026-09-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d2'
down_revision: Union[str, None] = 'f9b1d3e5a7c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    with op.batch_alter_table('broadcasts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('buttons', JSON, nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('broadcasts', schema=None) as batch_op:
        batch_op.drop_column('buttons')
