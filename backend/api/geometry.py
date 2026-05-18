import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db import get_db
from db.models import Job
from config import get_settings

router = APIRouter(prefix="/api/jobs", tags=["geometry"])
settings = get_settings()


@router.get("/{job_id}/geometry")
def get_geometry_params(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"geometry_params": job.geometry_params}


@router.get("/{job_id}/vtk")
def get_vtk(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.mesh_result:
        raise HTTPException(400, "Mesh not generated yet")
    vtk_file = job.mesh_result.get("vtk_file")
    if not vtk_file or not os.path.exists(vtk_file):
        raise HTTPException(404, "VTK file not found")
    return FileResponse(vtk_file, media_type="application/octet-stream")


@router.get("/{job_id}/surface")
def get_surface_stl(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.geometry_params:
        raise HTTPException(400, "Geometry not parsed yet")

    stl_path = os.path.join(settings.output_dir, f"{job_id}_surface.stl")

    if not os.path.exists(stl_path):
        from pipeline.geometry_exporter import export_surface_stl
        export_surface_stl(job.file_path, job.geometry_params, stl_path)

    return FileResponse(stl_path, media_type="model/stl", filename=f"{job_id}.stl")


@router.get("/{job_id}/mesh-preview")
def get_mesh_preview(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.mesh_result:
        raise HTTPException(400, "Mesh not generated yet")
    vtk_file = job.mesh_result.get("vtk_file", "")
    return {
        "vtk_url": f"/api/jobs/{job_id}/vtk",
        "vtk_file": vtk_file,
        "mesh_stats": {
            "element_count": job.mesh_result.get("element_count"),
            "max_aspect_ratio": job.mesh_result.get("max_aspect_ratio"),
        },
    }
