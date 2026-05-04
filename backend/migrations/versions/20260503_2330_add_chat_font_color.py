"""add_chat_font_color

Revision ID: 826dafea5494
Revises: 011_add_ict_config
Create Date: 2026-05-03 23:30:05.801554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '826dafea5494'
down_revision: Union[str, None] = '011_add_ict_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('chat_font_color', sa.String(length=20), nullable=True, default='#e2e8f0'))


def downgrade() -> None:
    op.drop_column('users', 'chat_font_color')
