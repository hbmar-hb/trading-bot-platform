"""add model_validation_logs table

Revision ID: b1c2d3e4f5g6h7i8j9k0l1m2n3o4p5q6r7
Revises: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q
Create Date: 2026-05-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6h7i8j9k0l1m2n3o4p5q6r7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'model_validation_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('model_version', sa.String(50), nullable=False),
        sa.Column('model_type', sa.String(30), nullable=False, server_default='anti_fake_xgb'),
        sa.Column('trained_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('samples_used', sa.Integer(), nullable=False),
        sa.Column('features_used', sa.Integer(), nullable=False),
        sa.Column('feature_names', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('wf_passed', sa.Boolean(), nullable=False),
        sa.Column('wf_reason', sa.Text(), nullable=False),
        sa.Column('wf_folds', sa.Integer(), nullable=False),
        sa.Column('wf_sharpe', sa.Float(), nullable=True),
        sa.Column('wf_profit_factor', sa.Float(), nullable=True),
        sa.Column('wf_expectancy', sa.Float(), nullable=True),
        sa.Column('wf_win_rate', sa.Float(), nullable=True),
        sa.Column('wf_max_drawdown', sa.Float(), nullable=True),
        sa.Column('wf_total_return', sa.Float(), nullable=True),
        sa.Column('wf_fold_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('old_sharpe', sa.Float(), nullable=True),
        sa.Column('old_profit_factor', sa.Float(), nullable=True),
        sa.Column('old_expectancy', sa.Float(), nullable=True),
        sa.Column('test_auc', sa.Float(), nullable=True),
        sa.Column('test_accuracy', sa.Float(), nullable=True),
        sa.Column('test_precision', sa.Float(), nullable=True),
        sa.Column('test_recall', sa.Float(), nullable=True),
        sa.Column('artifact_path', sa.Text(), nullable=True),
        sa.Column('top_features', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mvl_model_version', 'model_validation_logs', ['model_version'], unique=False)
    op.create_index('ix_mvl_model_type', 'model_validation_logs', ['model_type'], unique=False)
    op.create_index('ix_mvl_trained_at', 'model_validation_logs', ['trained_at'], unique=False)
    op.create_index('ix_mvl_wf_passed', 'model_validation_logs', ['wf_passed'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_mvl_wf_passed', table_name='model_validation_logs')
    op.drop_index('ix_mvl_trained_at', table_name='model_validation_logs')
    op.drop_index('ix_mvl_model_type', table_name='model_validation_logs')
    op.drop_index('ix_mvl_model_version', table_name='model_validation_logs')
    op.drop_table('model_validation_logs')
