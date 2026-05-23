"""clear follow-up sources for not-mentioned answers

Revision ID: 20260522_0004
Revises: 20260518_0003
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "20260522_0004"
down_revision = "20260518_0003"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = column_names("meetings")
    if {"follow_up_answer", "follow_up_sources_json"}.issubset(columns):
        op.execute(
            sa.text(
                """
                UPDATE meetings
                SET follow_up_sources_json = '[]'
                WHERE lower(trim(trailing '.' from trim(follow_up_answer))) = 'not mentioned'
                """
            )
        )


def downgrade() -> None:
    pass
