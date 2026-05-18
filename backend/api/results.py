from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from db.models import Job, JobStatus

router = APIRouter(prefix="/api/jobs", tags=["results"])


@router.get("/{job_id}/results")
def get_results(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(400, f"Job not completed (status: {job.status.value})")

    from pipeline.report_generator import generate_report
    return generate_report(job)
