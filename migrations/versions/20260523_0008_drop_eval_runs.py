"""drop prompt eval runs

Revision ID: 20260523_0008
Revises: 20260523_0007
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0008"
down_revision = "20260523_0007"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if table_exists(table_name) and not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if column_exists("audit_events", "action"):
        op.execute("DELETE FROM audit_events WHERE action = 'eval.run'")
    if column_exists("event_outbox", "event_type"):
        op.execute("DELETE FROM event_outbox WHERE event_type = 'eval.completed'")
    if column_exists("event_outbox", "topic"):
        op.execute("DELETE FROM event_outbox WHERE topic = 'eval.completed'")
    if table_exists("eval_runs"):
        op.drop_table("eval_runs")


def downgrade() -> None:
    if not table_exists("eval_runs"):
        op.create_table(
            "eval_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "prompt_version_id",
                sa.Integer(),
                sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("dataset_name", sa.String(length=120), nullable=False),
            sa.Column("pass_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("citation_coverage", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unsupported_claim_rate", sa.Float(), nullable=False, server_default="1"),
            sa.Column("json_validity_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("latency_p95_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="failed"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_eval_runs_status", "eval_runs", ["status"])
