"""drop unused operations tables

Revision ID: 20260523_0012
Revises: 20260523_0011
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0012"
down_revision = "20260523_0011"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if table_exists(table_name) and not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if table_exists("retention_policies"):
        op.drop_table("retention_policies")


def downgrade() -> None:
    if not table_exists("retention_policies"):
        op.create_table(
            "retention_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column("delete_behavior", sa.String(length=80), nullable=False, server_default="hard_delete"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_retention_policies_resource_type", "retention_policies", ["resource_type"])
