"""add jobs.step column

Revision ID: 0002_add_jobs_step
Revises: 0001_create_jobs_tasks
Create Date: 2026-02-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_jobs_step"
down_revision = "0001_create_jobs_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("step", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "step")
