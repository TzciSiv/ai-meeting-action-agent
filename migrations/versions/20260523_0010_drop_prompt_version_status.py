"""drop prompt version status

Revision ID: 20260523_0010
Revises: 20260523_0009
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0010"
down_revision = "20260523_0009"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if table_exists(table_name) and not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def drop_index_if_exists(index_name: str, table_name: str) -> None:
    if index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if "status" in column_names("prompt_versions"):
        drop_index_if_exists("ix_prompt_versions_status", "prompt_versions")
        op.drop_column("prompt_versions", "status")


def downgrade() -> None:
    if "status" not in column_names("prompt_versions"):
        op.add_column(
            "prompt_versions",
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        )
    create_index_if_missing("ix_prompt_versions_status", "prompt_versions", ["status"])
