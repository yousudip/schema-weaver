"""add purpose/description to jobs and create job_files table

Revision ID: 0005_multi_file_jobs
Revises: 0004_create_schema_vectors
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_multi_file_jobs"
down_revision = "0004_create_schema_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add purpose and description to existing jobs table
    op.add_column("jobs", sa.Column("purpose", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("description", sa.Text(), nullable=True))

    # Create job_files table for multi-file job support
    op.create_table(
        "job_files",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_files_job_id", "job_files", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_files_job_id", "job_files")
    op.drop_table("job_files")
    op.drop_column("jobs", "description")
    op.drop_column("jobs", "purpose")
