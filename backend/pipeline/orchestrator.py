import logging
from sqlalchemy.orm import Session

from db.models import Job, JobStatus
from pipeline.geometry_parser import parse_geometry
from pipeline.quality_checker import check_quality, adjust_seed_size
from deps import get_abaqus_runner

logger = logging.getLogger(__name__)

MAX_MESH_RETRIES = 5


def run_geometry_parse(job_id: str, db: Session) -> None:
    job = db.get(Job, job_id)
    try:
        params = parse_geometry(job.file_path)
        job.geometry_params = params
        job.mesh_params = {"seed_size": params.get("seed_size_recommendation", 5.0)}
        job.status = JobStatus.GEOMETRY_PARSED
        db.commit()
    except Exception as e:
        _fail(job, str(e), db)


def run_mesh(job_id: str, db: Session) -> None:
    job = db.get(Job, job_id)
    runner = get_abaqus_runner()
    params = dict(job.mesh_params or {})
    seed_size = params.get("seed_size", 5.0)
    case = job.case_type or "case1"

    for attempt in range(MAX_MESH_RETRIES):
        params["seed_size"] = seed_size
        job.status = JobStatus.MESHING
        db.commit()

        try:
            geo = job.geometry_params or {}
            if case == "case2":
                cut_planes = _get_approved_cuts(job_id, db)
                result = runner.run_mesh_case2(job.file_path, params, cut_planes,
                                               geometry_params=geo)
            else:
                result = runner.run_mesh_case1(job.file_path, params,
                                               geometry_params=geo)
        except Exception as e:
            _fail(job, str(e), db)
            return

        quality = check_quality(result, case)
        if quality["pass"]:
            job.mesh_result = result
            job.mesh_params = params
            job.status = JobStatus.MESH_DONE
            db.commit()
            logger.info("Job %s mesh done (attempt %d)", job_id, attempt + 1)
            return

        logger.warning("Job %s mesh quality failed attempt %d: %s", job_id, attempt + 1, quality["issues"])
        seed_size = adjust_seed_size(seed_size, quality["issues"])

    _fail(job, f"Mesh quality not met after {MAX_MESH_RETRIES} retries", db)


def run_solve(job_id: str, db: Session) -> None:
    job = db.get(Job, job_id)
    runner = get_abaqus_runner()

    try:
        job.status = JobStatus.SOLVING
        db.commit()

        vtk_file = (job.mesh_result or {}).get("vtk_file", "")
        inp_file = vtk_file.replace(".vtk", ".inp") if vtk_file else f"/tmp/{job_id}.inp"

        bc_result = runner.apply_bc(inp_file, job.bc_params or {})
        analysis = runner.submit_job(
            bc_result.get("modified_file", inp_file),
            geometry_params=job.geometry_params or {},
            bc_params=job.bc_params or {},
            case_type=job.case_type or "case1",
            mesh_result=job.mesh_result or {},
            cut_planes=_get_approved_cuts(job_id, db),
        )

        job.analysis_result = analysis
        job.status = JobStatus.COMPLETED
        db.commit()
    except Exception as e:
        _fail(job, str(e), db)


def _get_approved_cuts(job_id: str, db: Session) -> list[dict]:
    from db.models import CutSuggestion
    suggestion = (
        db.query(CutSuggestion)
        .filter(CutSuggestion.job_id == job_id, CutSuggestion.final_cut.isnot(None))
        .order_by(CutSuggestion.created_at.desc())
        .first()
    )
    if suggestion and suggestion.final_cut:
        return suggestion.final_cut.get("cut_planes", [])
    return []


def _fail(job: Job, message: str, db: Session) -> None:
    job.status = JobStatus.FAILED
    job.error_message = message
    db.commit()
    logger.error("Job %s failed: %s", job.id, message)
