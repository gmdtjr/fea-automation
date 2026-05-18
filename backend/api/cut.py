import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from db.models import Job, JobStatus, CutSuggestion

router = APIRouter(prefix="/api/jobs", tags=["cut"])


class ApprovePayload(BaseModel):
    cut_planes: list[dict]
    adjustment_mm: Optional[float] = 0.0


@router.get("/{job_id}/cut-suggestion")
async def get_cut_suggestion(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.case_type != "case2":
        raise HTTPException(400, "Cut suggestion is only for Case 2 jobs")

    existing = (
        db.query(CutSuggestion)
        .filter(CutSuggestion.job_id == job_id)
        .order_by(CutSuggestion.created_at.desc())
        .first()
    )
    if existing:
        return {
            "suggestion": existing.ai_suggestion,
            "final_cut": existing.final_cut,
            "confidence": existing.confidence,
        }

    if not job.geometry_params:
        raise HTTPException(400, "Geometry not parsed yet")

    job.status = JobStatus.AWAITING_CUT_REVIEW
    db.commit()

    # Resolve STL path for Vision rendering
    from config import get_settings
    stl_path = f"{get_settings().output_dir}/{job_id}_surface.stl"

    background_tasks.add_task(_bg_suggest, job_id, job.geometry_params, stl_path)
    return {"suggestion": None, "final_cut": None, "confidence": None, "pending": True}


@router.post("/{job_id}/cut-approve")
def approve_cut(
    job_id: str,
    payload: ApprovePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    suggestion = (
        db.query(CutSuggestion)
        .filter(CutSuggestion.job_id == job_id)
        .order_by(CutSuggestion.created_at.desc())
        .first()
    )
    if not suggestion:
        # Create record even if no AI suggestion was stored yet
        suggestion = CutSuggestion(
            id=str(uuid.uuid4()),
            job_id=job_id,
            geometry_params=job.geometry_params,
            ai_suggestion=None,
            created_at=datetime.utcnow(),
        )
        db.add(suggestion)

    suggestion.final_cut = {"cut_planes": payload.cut_planes}
    suggestion.adjustment_mm = payload.adjustment_mm or 0.0

    job.updated_at = datetime.utcnow()
    db.commit()

    background_tasks.add_task(_bg_mesh, job_id)
    return {"job_id": job_id, "status": "meshing"}


async def _bg_suggest(job_id: str, geometry_params: dict, stl_path: str | None = None):
    import logging
    from db import SessionLocal
    from ai.cut_advisor import suggest_cut_position, save_cut_suggestion, rule_based_fallback

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        try:
            suggestion = await suggest_cut_position(geometry_params, stl_path=stl_path)
        except Exception as e:
            logger.warning("Claude API failed (%s), using rule-based fallback", e)
            suggestion = rule_based_fallback(geometry_params)
        await save_cut_suggestion(job_id, geometry_params, suggestion, db)
    except Exception as e:
        logger.error("_bg_suggest failed for job %s: %s", job_id, e)
    finally:
        db.close()


def _bg_mesh(job_id: str):
    import asyncio
    from db import SessionLocal
    from pipeline.orchestrator import run_mesh
    db = SessionLocal()
    try:
        run_mesh(job_id, db)
    finally:
        db.close()

