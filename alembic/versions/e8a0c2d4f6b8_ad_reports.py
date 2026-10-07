"""ad reports: when an ad's report for the advertiser is due, and the numbers kept for it

Revision ID: e8a0c2d4f6b8
Revises: b3d5f7a9c1e3
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8a0c2d4f6b8'
down_revision: Union[str, None] = 'b3d5f7a9c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('publications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('report_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column(
            'ad_stats', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False, server_default='{}',
        ))
        batch_op.create_index('ix_publications_report_at', ['report_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('publications', schema=None) as batch_op:
        batch_op.drop_index('ix_publications_report_at')
        batch_op.drop_column('ad_stats')
        batch_op.drop_column('report_at')
