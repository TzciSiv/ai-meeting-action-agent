"""store ingestion job file size

Revision ID: 20260518_0003
Revises: 20260518_0002
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa


revision = "20260518_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "file_size_bytes" not in column_names("ingestion_jobs"):
        op.add_column(
            "ingestion_jobs",
            sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if "file_size_bytes" in column_names("ingestion_jobs"):
        op.drop_column("ingestion_jobs", "file_size_bytes")
