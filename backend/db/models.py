import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, JSON, Enum as SAEnum,
    DateTime, ForeignKey,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    GEOMETRY_PARSED = "geometry_parsed"
    AWAITING_CUT_REVIEW = "awaiting_cut_review"
    MESHING = "meshing"
    MESH_DONE = "mesh_done"
    SOLVING = "solving"
    COMPLETED = "completed"
    FAILED = "failed"


def new_uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=new_uuid)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    case_type = Column(String)                  # "case1" | "case2"
    status = Column(SAEnum(JobStatus), default=JobStatus.PENDING, nullable=False)
    geometry_params = Column(JSON)
    mesh_params = Column(JSON)
    bc_params = Column(JSON)
    mesh_result = Column(JSON)
    analysis_result = Column(JSON)
    ai_report = Column(String)
    error_message = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cut_suggestions = relationship("CutSuggestion", back_populates="job")


class CutSuggestion(Base):
    __tablename__ = "cut_suggestions"

    id = Column(String, primary_key=True, default=new_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    geometry_params = Column(JSON)
    ai_suggestion = Column(JSON)
    final_cut = Column(JSON)
    adjustment_mm = Column(Float)
    confidence = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="cut_suggestions")
