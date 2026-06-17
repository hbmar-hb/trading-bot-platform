"""Add trade_replay_snapshots and deployment_gate_logs tables.

Revision ID: 20260515_1800
Revises: 20260515_1700
Create Date: 2026-05-15 18:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260515_1800"
down_revision: Union[str, None] = "20260515_1700"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # trade_replay_snapshots
    op.create_table(
        "trade_replay_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("ai_signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_signals.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bot_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("features", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("fake_probability", sa.Numeric(10, 6), nullable=True),
        sa.Column("calibrated_confidence", sa.Numeric(10, 6), nullable=True),
        sa.Column("quality_tier", sa.String(20), nullable=True),
        sa.Column("anti_fake_status", sa.String(20), nullable=True),
        sa.Column("score", sa.Numeric(10, 4), nullable=True),
        sa.Column("quality_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("confluence_weights", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("regime", sa.String(30), nullable=True),
        sa.Column("regime_confidence", sa.Numeric(10, 4), nullable=True),
        sa.Column("htf_bias", sa.String(10), nullable=True),
        sa.Column("bot_config_snapshot", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("execution", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("gates_snapshot", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("ohlcv_context", postgresql.JSONB, nullable=True, server_default="[]"),
        sa.Column("funding_rate_at_exec", sa.Numeric(10, 6), nullable=True),
        sa.Column("spread_at_exec", sa.Numeric(10, 6), nullable=True),
        sa.Column("atr_value_at_exec", sa.Numeric(20, 8), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("model_artifact_path", sa.Text, nullable=True),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("direction", sa.String(10), nullable=True),
        sa.Column("timeframe", sa.String(10), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # deployment_gate_logs
    op.create_table(
        "deployment_gate_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("state", sa.String(20), nullable=False, index=True),
        sa.Column("sizing_multiplier", sa.Numeric(5, 2), nullable=False, server_default="1.00"),
        sa.Column("sharpe_20", sa.Numeric(10, 4), nullable=True),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("drift_psi_max", sa.Numeric(10, 4), nullable=True),
        sa.Column("wf_passed", sa.Boolean, nullable=True),
        sa.Column("confidence_decay_divergence", sa.Numeric(10, 4), nullable=True),
        sa.Column("reasons", postgresql.JSONB, nullable=True, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False, index=True),
        sa.Index("idx_deployment_gate_state_created", "state", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("deployment_gate_logs")
    op.drop_table("trade_replay_snapshots")
