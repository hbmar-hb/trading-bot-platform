"""Add alert trigger fields to bot_configs

Revision ID: 20260507_0018
Revises: 017_position_source
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = '018_bot_alert_trigger'
down_revision = '017_position_source'
branch_labels = None
depends_on = None


def upgrade():
    # trigger_indicator: qué indicador activa el bot (None = desactivado)
    op.add_column('bot_configs', sa.Column(
        'trigger_indicator', sa.String(50), nullable=True, server_default=None
    ))
    # trigger_timeframe: TF del scan (si None, usa el bot.timeframe)
    op.add_column('bot_configs', sa.Column(
        'trigger_timeframe', sa.String(10), nullable=True, server_default=None
    ))
    # trigger_min_grade: grade mínimo para disparar ("A+", "A", "A-")
    op.add_column('bot_configs', sa.Column(
        'trigger_min_grade', sa.String(5), nullable=False, server_default='A'
    ))
    # trigger_timing: cuándo evaluar la señal
    op.add_column('bot_configs', sa.Column(
        'trigger_timing', sa.String(20), nullable=False, server_default='candle_close'
    ))
    # trigger_interval_minutes: intervalo en minutos para modo intracandle
    op.add_column('bot_configs', sa.Column(
        'trigger_interval_minutes', sa.Integer, nullable=False, server_default='5'
    ))
    # min_confirm_candles: velas de confirmación antes de disparar
    op.add_column('bot_configs', sa.Column(
        'min_confirm_candles', sa.Integer, nullable=False, server_default='1'
    ))

    # Migrar bots que ya tenían ict_scan_enabled=True al nuevo sistema
    op.execute(
        "UPDATE bot_configs SET trigger_indicator = 'ict' WHERE ict_scan_enabled = TRUE"
    )


def downgrade():
    op.drop_column('bot_configs', 'min_confirm_candles')
    op.drop_column('bot_configs', 'trigger_interval_minutes')
    op.drop_column('bot_configs', 'trigger_timing')
    op.drop_column('bot_configs', 'trigger_min_grade')
    op.drop_column('bot_configs', 'trigger_timeframe')
    op.drop_column('bot_configs', 'trigger_indicator')
