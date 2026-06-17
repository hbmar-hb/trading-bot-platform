"""add_fake_probability

Revision ID: 1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
Revises: 085894bfae254bc0989ffc00a0fb38a5
Create Date: 2026-05-13 14:37:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p'
down_revision: Union[str, None] = '085894bfae254bc0989ffc00a0fb38a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_signals ADD COLUMN IF NOT EXISTS fake_probability FLOAT"
    )


def downgrade() -> None:
    op.drop_column('ai_signals', 'fake_probability')
