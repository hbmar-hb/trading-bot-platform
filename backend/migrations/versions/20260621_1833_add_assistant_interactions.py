"""add assistant_interactions table

Revision ID: 20260621_1833
Revises: 20260612_1908
Create Date: 2026-06-21 18:33:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260621_1833'
down_revision = '20260612_1908'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'assistant_interactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('source_scope', sa.String(length=20), nullable=False),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('was_streamed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('feedback', sa.Integer(), nullable=True),
        sa.Column('feedback_comment', sa.Text(), nullable=True),
        sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assistant_interactions_feedback'), 'assistant_interactions', ['feedback'], unique=False)
    op.create_index(op.f('ix_assistant_interactions_source_scope'), 'assistant_interactions', ['source_scope'], unique=False)
    op.create_index(op.f('ix_assistant_interactions_user_id'), 'assistant_interactions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_assistant_interactions_user_id'), table_name='assistant_interactions')
    op.drop_index(op.f('ix_assistant_interactions_source_scope'), table_name='assistant_interactions')
    op.drop_index(op.f('ix_assistant_interactions_feedback'), table_name='assistant_interactions')
    op.drop_table('assistant_interactions')
