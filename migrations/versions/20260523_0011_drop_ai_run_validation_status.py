"""drop ai run validation status

Revision ID: 20260523_0011
Revises: 20260523_0010
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0011"
down_revision = "20260523_0010"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = column_names("ai_runs")
    if "needs_review" in columns:
        op.drop_column("ai_runs", "needs_review")
    if "validation_status" in columns:
        op.drop_column("ai_runs", "validation_status")


def downgrade() -> None:
    columns = column_names("ai_runs")
    if "validation_status" not in columns:
        op.add_column(
            "ai_runs",
            sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="not_validated"),
        )
    if "needs_review" not in columns:
        op.add_column(
            "ai_runs",
            sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
