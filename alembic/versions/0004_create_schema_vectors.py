"""create schema_vectors table

Revision ID: 0004_create_schema_vectors
Revises: 0003_add_jobs_analysis
Create Date: 2026-02-05
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0004_create_schema_vectors"
down_revision = "0003_add_jobs_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "schema_vectors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("suggested_name", sa.String(), nullable=True),
        sa.Column("inferred_type", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("representation", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schema_vectors")
