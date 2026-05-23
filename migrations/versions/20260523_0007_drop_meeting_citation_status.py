"""drop meeting citation status fields

Revision ID: 20260523_0007
Revises: 20260523_0006
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0007"
down_revision = "20260523_0006"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    if column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_exists(table_name) and not column_exists(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    drop_column_if_exists("meetings", "needs_review")
    drop_column_if_exists("meetings", "evidence_status")
    drop_column_if_exists("meetings", "validation_status")
    drop_column_if_exists("meetings", "citations_json")


def downgrade() -> None:
    add_column_if_missing("meetings", sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"))
    add_column_if_missing(
        "meetings",
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="not_validated"),
    )
    add_column_if_missing(
        "meetings",
        sa.Column("evidence_status", sa.String(length=40), nullable=False, server_default="not_checked"),
    )
    add_column_if_missing("meetings", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
