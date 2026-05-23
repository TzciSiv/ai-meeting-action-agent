"""kafka pipeline records

Revision ID: 20260518_0002
Revises: 20260518_0001
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa


revision = "20260518_0002"
down_revision = "20260518_0001"
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


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    if column_name in column_names(table_name):
        op.drop_column(table_name, column_name)


def drop_table_if_exists(table_name: str) -> None:
    if table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    add_column_if_missing("meetings", sa.Column("embedding_model", sa.String(length=120), nullable=False, server_default=""))
    add_column_if_missing("meetings", sa.Column("chunking_version", sa.String(length=80), nullable=False, server_default=""))
    add_column_if_missing(
        "meetings",
        sa.Column("embedding_status", sa.String(length=40), nullable=False, server_default="not_started"),
    )
    add_column_if_missing("meetings", sa.Column("last_embedded_at", sa.DateTime(timezone=True), nullable=True))

    if not table_exists("ingestion_jobs"):
        op.create_table(
            "ingestion_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.String(length=80), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_type", sa.String(length=40), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_uri", sa.Text(), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("follow_up_question", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
            sa.Column("current_step", sa.String(length=80), nullable=False, server_default="queued"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_ingestion_jobs_job_id", "ingestion_jobs", ["job_id"], unique=True)
    create_index_if_missing("ix_ingestion_jobs_user_id", "ingestion_jobs", ["user_id"])
    create_index_if_missing("ix_ingestion_jobs_meeting_id", "ingestion_jobs", ["meeting_id"])
    create_index_if_missing("ix_ingestion_jobs_source_type", "ingestion_jobs", ["source_type"])
    create_index_if_missing("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    if not table_exists("event_outbox"):
        op.create_table(
            "event_outbox",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.String(length=80), nullable=False, unique=True),
            sa.Column("topic", sa.String(length=120), nullable=False),
            sa.Column("key", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("event_version", sa.String(length=20), nullable=False, server_default="1"),
            sa.Column("envelope_json", sa.Text(), nullable=False),
            sa.Column("publish_status", sa.String(length=40), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing("ix_event_outbox_event_id", "event_outbox", ["event_id"], unique=True)
    create_index_if_missing("ix_event_outbox_topic", "event_outbox", ["topic"])
    create_index_if_missing("ix_event_outbox_key", "event_outbox", ["key"])
    create_index_if_missing("ix_event_outbox_event_type", "event_outbox", ["event_type"])
    create_index_if_missing("ix_event_outbox_publish_status", "event_outbox", ["publish_status"])


def downgrade() -> None:
    drop_table_if_exists("event_outbox")
    drop_table_if_exists("ingestion_jobs")
    drop_column_if_exists("meetings", "last_embedded_at")
    drop_column_if_exists("meetings", "embedding_status")
    drop_column_if_exists("meetings", "chunking_version")
    drop_column_if_exists("meetings", "embedding_model")
