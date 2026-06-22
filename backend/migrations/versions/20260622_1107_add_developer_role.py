"""add developer role

Revision ID: 20260622_1107
Revises: 20260621_1833
Create Date: 2026-06-22 11:07:00.000000+00:00
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20260622_1107'
down_revision = '20260621_1833'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eliminar el constraint anterior e insertar el nuevo con el rol developer
    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('rol1', 'moderator', 'admin', 'developer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('rol1', 'moderator', 'admin')",
    )
