from __future__ import annotations

from sqlalchemy import Column, DateTime, JSON, String, Text, func
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    status = Column(String, nullable=False)
    task_status = Column(String, nullable=False)
    step = Column(String, nullable=True)
    analysis = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=True)
    task_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SchemaVector(Base):
    __tablename__ = "schema_vectors"

    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=True)
    source_name = Column(String, nullable=False)
    suggested_name = Column(String, nullable=True)
    inferred_type = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    representation = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
