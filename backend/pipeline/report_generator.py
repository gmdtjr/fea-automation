from datetime import datetime


def generate_report(job) -> dict:
    """Build a structured report dict from a completed job."""
    result = job.analysis_result or {}
    geo = job.geometry_params or {}
    mesh = job.mesh_result or {}

    return {
        "job_id": job.id,
        "file_name": job.file_name,
        "case_type": job.case_type,
        "generated_at": datetime.utcnow().isoformat(),
        "geometry_summary": {
            "header_OD_mm": round((geo.get("header_pipe", {}).get("outer_radius", 0)) * 2000, 1),
            "branch_OD_mm": round((geo.get("branch_pipe", {}).get("outer_radius", 0)) * 2000, 1),
            "branch_angle_deg": geo.get("branch_pipe", {}).get("angle_deg"),
        },
        "mesh_summary": {
            "element_count": mesh.get("element_count"),
            "max_aspect_ratio": mesh.get("max_aspect_ratio"),
            "min_jacobian": mesh.get("min_jacobian"),
            "execution_time_s": mesh.get("execution_time"),
        },
        "analysis_summary": {
            "max_mises_MPa": result.get("max_mises"),
            "max_displacement_mm": result.get("max_displacement"),
            "critical_location": result.get("max_stress_location"),
            "allowable_stress": result.get("allowable_stress"),
            "safety_factor": result.get("safety_factor"),
            "sif": result.get("sif"),
            "sigma_hoop_header_mpa": result.get("sigma_hoop_header_mpa"),
            "pressure_mpa": result.get("pressure_mpa"),
        },
        "ai_report": job.ai_report,
    }
