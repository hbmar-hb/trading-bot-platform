"""Fase 1: relax restrictive AI bot configs.

Revision ID: 20260613_1200
Revises: 20260612_1908
Create Date: 2026-06-13 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '20260613_1200'
down_revision = '20260612_1908'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Relaxes the most restrictive ai_signal_config gates for active AI bots.

    This is a one-time corrective migration (Fase 1). It widens filtering so
    that bots stop rejecting signals purely by tier/status/score/confluence.
    """
    conn = op.get_bind()

    conn.execute(sa.text("""
        UPDATE bot_configs
        SET ai_signal_config = jsonb_set(
            jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    COALESCE(ai_signal_config, '{}'::jsonb),
                                    '{min_score}', '55'::jsonb, true
                                ),
                                '{require_clear}', 'false'::jsonb, true
                            ),
                            '{max_concurrent}', '2'::jsonb, true
                        ),
                        '{allowed_tiers}', '["STRONG", "MODERATE"]'::jsonb, true
                    ),
                    '{allowed_statuses}', '["CLEAR", "CAUTION"]'::jsonb, true
                ),
                '{confluence,require_htf_alignment}', 'false'::jsonb, true
            ),
            '{confluence,require_liquidity_sweep,enabled}', 'false'::jsonb, true
        )
        WHERE ai_signal_mode = TRUE
          AND status IN ('active', 'paused');
    """))

    conn.execute(sa.text("""
        UPDATE bot_configs
        SET ai_signal_config = jsonb_set(
            jsonb_set(
                ai_signal_config,
                '{confluence,asia_gate_enabled}', 'false'::jsonb, true
            ),
            '{confluence,killzone_gate_mode}', '"disabled"'::jsonb, true
        )
        WHERE ai_signal_mode = TRUE
          AND status IN ('active', 'paused');
    """))


def downgrade() -> None:
    """No automatic downgrade: reverting to restrictive defaults is destructive."""
    pass
