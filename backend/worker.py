from celery import Celery
from config import get_settings

settings = get_settings()
celery_app = Celery("fea_worker", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="worker.tasks.parse_geometry")
def parse_geometry(job_id: str):
    from db import SessionLocal
    from pipeline.orchestrator import run_geometry_parse
    db = SessionLocal()
    try:
        run_geometry_parse(job_id, db)
    finally:
        db.close()


@celery_app.task(name="worker.tasks.run_mesh")
def run_mesh(job_id: str):
    from db import SessionLocal
    from pipeline.orchestrator import run_mesh as _run_mesh
    db = SessionLocal()
    try:
        _run_mesh(job_id, db)
    finally:
        db.close()


@celery_app.task(name="worker.tasks.run_solve")
def run_solve(job_id: str):
    import asyncio
    from db import SessionLocal
    from db.models import Job, JobStatus
    from pipeline.orchestrator import run_solve as _run_solve
    from ai.result_analyzer import analyze_results

    db = SessionLocal()
    try:
        _run_solve(job_id, db)
        job = db.get(Job, job_id)
        if job and job.status == JobStatus.COMPLETED and job.analysis_result:
            report = asyncio.run(analyze_results(job.analysis_result, job.geometry_params or {}))
            job.ai_report = report
            db.commit()
    finally:
        db.close()
