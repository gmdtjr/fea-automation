import os
import uuid
import shutil
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from db.models import Job, JobStatus
from pipeline.geometry_parser import SUPPORTED_FORMATS
from config import get_settings

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
settings = get_settings()


class CaseTypePayload(BaseModel):
    case_type: str  # "case1" | "case2"


class JobOut(BaseModel):
    id: str
    file_name: str
    case_type: Optional[str]
    status: str
    geometry_params: Optional[dict]
    mesh_params: Optional[dict]
    bc_params: Optional[dict]
    mesh_result: Optional[dict]
    analysis_result: Optional[dict]
    ai_report: Optional[str]
    error_message: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


def _to_out(job: Job) -> dict:
    return {
        "id": job.id,
        "file_name": job.file_name,
        "case_type": job.case_type,
        "status": job.status.value if job.status else None,
        "geometry_params": job.geometry_params,
        "mesh_params": job.mesh_params,
        "bc_params": job.bc_params,
        "mesh_result": job.mesh_result,
        "analysis_result": job.analysis_result,
        "ai_report": job.ai_report,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"Unsupported format: {ext}. Supported: {SUPPORTED_FORMATS}")

    job_id = str(uuid.uuid4())
    # Save uploads to output_dir, NOT watch_dir — avoids duplicate job from file_watcher
    upload_dir = os.path.join(settings.output_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, f"{job_id}{ext}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job = Job(
        id=job_id,
        file_name=file.filename,
        file_path=dest,
        status=JobStatus.PENDING,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()

    background_tasks.add_task(_bg_parse, job_id)
    return {"job_id": job_id, "status": "pending"}


@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [_to_out(j) for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _to_out(job)


@router.post("/{job_id}/case-type")
def set_case_type(
    job_id: str,
    payload: CaseTypePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if payload.case_type not in ("case1", "case2"):
        raise HTTPException(400, "case_type must be 'case1' or 'case2'")
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    job.case_type = payload.case_type
    job.updated_at = datetime.utcnow()
    db.commit()

    if payload.case_type == "case1":
        background_tasks.add_task(_bg_mesh, job_id)

    return {"job_id": job_id, "case_type": payload.case_type}


@router.post("/{job_id}/bc-params")
def set_bc_params(
    job_id: str,
    bc: dict,
    db: Session = Depends(get_db),
):
    """Save BC / material / load parameters before solving."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    from datetime import datetime
    job.bc_params = bc
    job.updated_at = datetime.utcnow()
    db.commit()
    return {"job_id": job_id, "bc_params": bc}


@router.post("/{job_id}/start-solve")
def start_solve(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.MESH_DONE:
        raise HTTPException(400, "Mesh must be completed before solving")

    background_tasks.add_task(_bg_solve, job_id)
    return {"job_id": job_id, "status": "solving"}


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Delete related cut suggestions
    from db.models import CutSuggestion
    db.query(CutSuggestion).filter(CutSuggestion.job_id == job_id).delete()

    # Delete associated files (VTK, STL, uploaded file)
    import glob
    files_to_delete = (
        glob.glob(f"{settings.output_dir}/{job_id}*.vtk") +
        glob.glob(f"{settings.output_dir}/{job_id}*.stl") +
        glob.glob(f"{settings.output_dir}/uploads/{job_id}.*")
    )
    for f in files_to_delete:
        try:
            os.remove(f)
        except OSError:
            pass

    db.delete(job)
    db.commit()
    return {"deleted": job_id}


@router.get("/{job_id}/history")
def get_job_history(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    from db.models import CutSuggestion
    cut_suggestions = (
        db.query(CutSuggestion)
        .filter(CutSuggestion.job_id == job_id)
        .order_by(CutSuggestion.created_at.asc())
        .all()
    )

    steps = []

    # Step 1: Upload
    steps.append({
        "step": "uploaded",
        "label": "파일 업로드",
        "timestamp": job.created_at.isoformat() if job.created_at else None,
        "data": {"file_name": job.file_name, "file_path": job.file_path},
    })

    # Step 2: Geometry parse
    if job.geometry_params:
        steps.append({
            "step": "geometry_parsed",
            "label": "형상 파싱",
            "timestamp": job.created_at.isoformat() if job.created_at else None,
            "data": {"geometry_params": job.geometry_params, "case_type": job.case_type},
        })

    # Step 3: Cut suggestions (all iterations)
    for idx, sug in enumerate(cut_suggestions):
        steps.append({
            "step": "cut_suggestion",
            "label": f"커팅 제안 #{idx + 1}",
            "timestamp": sug.created_at.isoformat() if sug.created_at else None,
            "data": {
                "ai_suggestion": sug.ai_suggestion,
                "final_cut": sug.final_cut,
                "adjustment_mm": sug.adjustment_mm,
                "confidence": sug.confidence,
            },
        })

    # Step 4: Mesh
    if job.mesh_result:
        steps.append({
            "step": "mesh_done",
            "label": "메시 생성",
            "timestamp": job.updated_at.isoformat() if job.updated_at else None,
            "data": {
                "mesh_result": job.mesh_result,
                "mesh_params": job.mesh_params,
                "vtk_url": f"/api/jobs/{job_id}/vtk" if job.mesh_result.get("vtk_file") else None,
            },
        })

    # Step 5: Analysis + report
    if job.analysis_result:
        steps.append({
            "step": "completed",
            "label": "해석 결과",
            "timestamp": job.updated_at.isoformat() if job.updated_at else None,
            "data": {
                "analysis_result": job.analysis_result,
                "ai_report": job.ai_report,
            },
        })

    return {"job_id": job_id, "status": job.status.value, "steps": steps}


@router.get("/{job_id}/results")
def get_results(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(400, f"Job not completed yet (status: {job.status.value})")

    from pipeline.report_generator import generate_report
    return generate_report(job)


def _bg_parse(job_id: str):
    from db import SessionLocal
    from pipeline.orchestrator import run_geometry_parse
    db = SessionLocal()
    try:
        run_geometry_parse(job_id, db)
    finally:
        db.close()


def _bg_mesh(job_id: str):
    from db import SessionLocal
    from pipeline.orchestrator import run_mesh
    db = SessionLocal()
    try:
        run_mesh(job_id, db)
    finally:
        db.close()


async def _bg_solve(job_id: str):
    from db import SessionLocal
    from pipeline.orchestrator import run_solve
    from ai.result_analyzer import analyze_results
    import asyncio
    db = SessionLocal()
    try:
        run_solve(job_id, db)
        job = db.get(Job, job_id)
        if job and job.status == JobStatus.COMPLETED and job.analysis_result:
            report = await analyze_results(job.analysis_result, job.geometry_params or {})
            job.ai_report = report
            db.commit()
    finally:
        db.close()
