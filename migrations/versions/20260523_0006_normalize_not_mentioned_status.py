"""normalize not-mentioned follow-up status

Revision ID: 20260523_0006
Revises: 20260522_0005
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260523_0006"
down_revision = "20260522_0005"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def column_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    meeting_columns = column_names("meetings")
    if {"validation_status", "evidence_status", "citations_json"}.issubset(meeting_columns):
        op.execute(
            sa.text(
                """
                UPDATE meetings
                SET validation_status = 'passed',
                    evidence_status = CASE
                        WHEN citations_json IS NOT NULL AND citations_json <> '[]' THEN 'supported'
                        ELSE 'not_checked'
                    END
                WHERE validation_status = 'insufficient_evidence'
                   OR evidence_status = 'insufficient_evidence'
                """
            )
        )

    ai_run_columns = column_names("ai_runs")
    if "validation_status" in ai_run_columns:
        op.execute(
            sa.text(
                """
                UPDATE ai_runs
                SET validation_status = 'passed',
                    needs_review = false
                WHERE validation_status = 'insufficient_evidence'
                """
            )
        )


def downgrade() -> None:
    pass
