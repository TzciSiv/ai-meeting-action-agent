"""add worker heartbeat records

Revision ID: 20260523_0009
Revises: 20260523_0008
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0009"
down_revision = "20260523_0008"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if table_exists(table_name) and not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not table_exists("worker_heartbeats"):
        op.create_table(
            "worker_heartbeats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("worker_id", sa.String(length=160), nullable=False, unique=True),
            sa.Column("display_name", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("hostname", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("mode", sa.String(length=40), nullable=False, server_default="kafka"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="starting"),
            sa.Column("current_topic", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("current_job_id", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("current_event_type", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    create_index_if_missing("ix_worker_heartbeats_worker_id", "worker_heartbeats", ["worker_id"], unique=True)
    create_index_if_missing("ix_worker_heartbeats_status", "worker_heartbeats", ["status"])
    create_index_if_missing("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])


def downgrade() -> None:
    if table_exists("worker_heartbeats"):
        op.drop_table("worker_heartbeats")
