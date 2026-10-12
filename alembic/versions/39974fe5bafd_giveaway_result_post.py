"""giveaway result post: once a giveaway's winners are announced, it can't get auto results again

Revision ID: 39974fe5bafd
Revises: b3bd4d9431c1
Create Date: 2026-10-12 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '39974fe5bafd'
down_revision: Union[str, None] = 'b3bd4d9431c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('giveaways', schema=None) as batch_op:
        batch_op.add_column(sa.Column('result_post_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_giveaways_result_post_id_posts', 'posts', ['result_post_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('giveaways', schema=None) as batch_op:
        batch_op.drop_constraint('fk_giveaways_result_post_id_posts', type_='foreignkey')
        batch_op.drop_column('result_post_id')
