"""commenters of a publication, the entrants of a comment giveaway

Revision ID: c7e9b1d3f5a7
Revises: b5d7f9a1c3e5
Create Date: 2026-09-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7e9b1d3f5a7'
down_revision: Union[str, None] = 'b5d7f9a1c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table(
        'commenters',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('publication_id', sa.Integer(), nullable=False),
        sa.Column('user_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=False),
        sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('publication_id', 'user_tg_id', name='uq_commenters_publication_user'),
    )
    op.create_index(op.f('ix_commenters_publication_id'), 'commenters', ['publication_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_commenters_publication_id'), table_name='commenters')
    op.drop_table('commenters')
