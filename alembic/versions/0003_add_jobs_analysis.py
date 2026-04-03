"""add jobs.analysis column

Revision ID: 0003_add_jobs_analysis
Revises: 0002_add_jobs_step
Create Date: 2026-02-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_jobs_analysis"
down_revision = "0002_add_jobs_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("analysis", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "analysis")
