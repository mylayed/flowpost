"""answers to the quizzes made of buttons under a post

Revision ID: ce1df64007df
Revises: a4c6e8f0b2d4
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ce1df64007df'
down_revision: Union[str, None] = 'a4c6e8f0b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table(
        'quiz_votes',
        sa.Column('id', PK, autoincrement=True, nullable=False),
        sa.Column('post_id', PK, nullable=False),
        sa.Column('quiz', sa.String(length=16), nullable=False),
        sa.Column('answer', sa.String(length=16), nullable=False),
        sa.Column('user_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('post_id', 'quiz', 'user_tg_id', name='uq_quiz_votes_post_quiz_user'),
    )
    op.create_index(op.f('ix_quiz_votes_post_id'), 'quiz_votes', ['post_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quiz_votes_post_id'), table_name='quiz_votes')
    op.drop_table('quiz_votes')
