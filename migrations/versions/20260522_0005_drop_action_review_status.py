"""drop action review status

Revision ID: 20260522_0005
Revises: 20260522_0004
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "20260522_0005"
down_revision = "20260522_0004"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "review_status" in column_names("action_items"):
        op.drop_column("action_items", "review_status")


def downgrade() -> None:
    if "review_status" not in column_names("action_items"):
        op.add_column(
            "action_items",
            sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"),
        )
