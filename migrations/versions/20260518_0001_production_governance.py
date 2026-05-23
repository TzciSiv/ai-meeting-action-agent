"""production governance records

Revision ID: 20260518_0001
Revises:
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa


revision = "20260518_0001"
down_revision = None
branch_labels = None
depends_on = None


# Local development databases may have been created with SQLAlchemy create_all
# before Alembic existed, so these migrations need to be safe to replay.
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


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in column_names(table_name):
        op.add_column(table_name, column)


def create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if table_exists(table_name) and not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def copy_column_if_possible(
    table_name: str,
    target_column: str,
    source_column: str,
    copy_blank_strings: bool = False,
) -> None:
    columns = column_names(table_name)
    if target_column in columns and source_column in columns:
        condition = f"{target_column} IS NULL"
        if copy_blank_strings:
            condition = f"({condition} OR {target_column} = '')"
        op.execute(f"UPDATE {table_name} SET {target_column} = {source_column} WHERE {condition}")


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    if column_name in column_names(table_name):
        op.drop_column(table_name, column_name)


def drop_table_if_exists(table_name: str) -> None:
    if table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    add_column_if_missing("users", sa.Column("role", sa.String(length=40), nullable=False, server_default="owner"))

    add_column_if_missing("meetings", sa.Column("ai_run_ids_json", sa.Text(), nullable=False, server_default="[]"))
    add_column_if_missing("meetings", sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"))
    add_column_if_missing("meetings", sa.Column("prompt_version", sa.String(length=120), nullable=False, server_default=""))
    add_column_if_missing("meetings", sa.Column("model", sa.String(length=120), nullable=False, server_default=""))
    add_column_if_missing(
        "meetings",
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="not_validated"),
    )
    add_column_if_missing(
        "meetings",
        sa.Column("evidence_status", sa.String(length=40), nullable=False, server_default="not_checked"),
    )
    add_column_if_missing("meetings", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    add_column_if_missing("meetings", sa.Column("generation_latency_ms", sa.Integer(), nullable=False, server_default="0"))

    add_column_if_missing(
        "action_items",
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"),
    )
    add_column_if_missing("action_items", sa.Column("source_run_id", sa.String(length=80), nullable=False, server_default=""))

    add_column_if_missing("audit_events", sa.Column("actor_user_id", sa.Integer(), nullable=True))
    add_column_if_missing("audit_events", sa.Column("action", sa.String(length=80), nullable=False, server_default=""))
    add_column_if_missing("audit_events", sa.Column("resource_type", sa.String(length=80), nullable=False, server_default=""))
    add_column_if_missing("audit_events", sa.Column("resource_id", sa.String(length=80), nullable=False, server_default=""))
    add_column_if_missing("audit_events", sa.Column("ip_hash", sa.String(length=80), nullable=False, server_default=""))
    add_column_if_missing("audit_events", sa.Column("user_agent_hash", sa.String(length=80), nullable=False, server_default=""))
    copy_column_if_possible("audit_events", "actor_user_id", "user_id")
    copy_column_if_possible("audit_events", "action", "event_type", copy_blank_strings=True)
    copy_column_if_possible("audit_events", "resource_type", "entity_type", copy_blank_strings=True)
    copy_column_if_possible("audit_events", "resource_id", "entity_id", copy_blank_strings=True)

    if not table_exists("meeting_permissions"):
        op.create_table(
            "meeting_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("access_level", sa.String(length=40), nullable=False, server_default="reviewer"),
            sa.Column("can_view_transcript", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_meeting_permissions_meeting_id", "meeting_permissions", ["meeting_id"])
    create_index_if_missing("ix_meeting_permissions_user_id", "meeting_permissions", ["user_id"])

    if not table_exists("prompt_versions"):
        op.create_table(
            "prompt_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("prompt_id", sa.String(length=120), nullable=False),
            sa.Column("version", sa.String(length=80), nullable=False),
            sa.Column("task_type", sa.String(length=80), nullable=False),
            sa.Column("model", sa.String(length=120), nullable=False),
            sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
            sa.Column("template_hash", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_prompt_versions_prompt_id", "prompt_versions", ["prompt_id"])
    create_index_if_missing("ix_prompt_versions_status", "prompt_versions", ["status"])

    if not table_exists("ai_runs"):
        op.create_table(
            "ai_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(length=80), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True),
            sa.Column(
                "prompt_version_id",
                sa.Integer(),
                sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("retrieved_chunk_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("output_hash", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="not_validated"),
            sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_estimate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_ai_runs_run_id", "ai_runs", ["run_id"], unique=True)
    create_index_if_missing("ix_ai_runs_meeting_id", "ai_runs", ["meeting_id"])
    create_index_if_missing("ix_ai_runs_user_id", "ai_runs", ["user_id"])

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

    if not table_exists("retention_policies"):
        op.create_table(
            "retention_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column("delete_behavior", sa.String(length=80), nullable=False, server_default="hard_delete"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    drop_table_if_exists("retention_policies")
    drop_table_if_exists("eval_runs")
    drop_table_if_exists("ai_runs")
    drop_table_if_exists("prompt_versions")
    drop_table_if_exists("meeting_permissions")
    drop_column_if_exists("audit_events", "user_agent_hash")
    drop_column_if_exists("audit_events", "ip_hash")
    drop_column_if_exists("audit_events", "resource_id")
    drop_column_if_exists("audit_events", "resource_type")
    drop_column_if_exists("audit_events", "action")
    drop_column_if_exists("audit_events", "actor_user_id")
    drop_column_if_exists("action_items", "source_run_id")
    drop_column_if_exists("action_items", "review_status")
    drop_column_if_exists("meetings", "generation_latency_ms")
    drop_column_if_exists("meetings", "needs_review")
    drop_column_if_exists("meetings", "evidence_status")
    drop_column_if_exists("meetings", "validation_status")
    drop_column_if_exists("meetings", "model")
    drop_column_if_exists("meetings", "prompt_version")
    drop_column_if_exists("meetings", "citations_json")
    drop_column_if_exists("meetings", "ai_run_ids_json")
    drop_column_if_exists("users", "role")
