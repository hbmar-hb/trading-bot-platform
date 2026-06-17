"""Expand trigger_min_grade to support comma-separated multi-grade values

Revision ID: 20260508_0019
Revises: 018_bot_alert_trigger
Create Date: 2026-05-08

"""
from alembic import op
import sqlalchemy as sa

revision = '019_trigger_grade_multivalue'
down_revision = '018_bot_alert_trigger'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'bot_configs', 'trigger_min_grade',
        type_=sa.String(20),
        existing_nullable=False,
        server_default='A+,A,A-',
    )
    # Migrar valor 'A' antiguo (calidad media) al nuevo default multivalor
    op.execute("UPDATE bot_configs SET trigger_min_grade = 'A+,A,A-' WHERE trigger_min_grade = 'A'")
    op.execute("UPDATE bot_configs SET trigger_min_grade = 'A+,A' WHERE trigger_min_grade = 'A+'")
    op.execute("UPDATE bot_configs SET trigger_min_grade = 'A,A-' WHERE trigger_min_grade = 'A-'")


def downgrade():
    op.alter_column(
        'bot_configs', 'trigger_min_grade',
        type_=sa.String(5),
        existing_nullable=False,
        server_default='A',
    )
