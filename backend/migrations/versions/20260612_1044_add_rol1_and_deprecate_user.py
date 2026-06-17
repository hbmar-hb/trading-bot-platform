"""add rol1 role and deprecate user role

Revision ID: 20260612_1044
Revises: 20260611_1643
Create Date: 2026-06-12 10:44:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260612_1044'
down_revision = '20260611_1643'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrar usuarios con el antiguo rol 'user' al nuevo rol 'rol1'
    op.execute("UPDATE users SET role = 'rol1' WHERE role = 'user'")

    # Cambiar el valor por defecto de la columna role a 'rol1'
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'rol1'")

    # Asegurar que solo existan roles válidos en la tabla
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('rol1', 'moderator', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'rol1'")
