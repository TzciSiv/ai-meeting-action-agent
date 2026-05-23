"""remove auditor role

Revision ID: 20260523_0013
Revises: 20260523_0012
Create Date: 2026-05-23
"""
from alembic import op


revision = "20260523_0013"
down_revision = "20260523_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'owner' WHERE role = 'auditor'")
    op.execute("UPDATE meeting_permissions SET access_level = 'reviewer' WHERE access_level = 'auditor'")


def downgrade() -> None:
    pass
