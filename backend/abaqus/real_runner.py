"""
RealAbaqusRunner — calls actual Abaqus CAE via subprocess.
Activated when ABAQUS_MODE=real in .env.

All methods match MockAbaqusRunner signatures exactly.
Switch: deps.py get_abaqus_runner() → RealAbaqusRunner(abaqus_path, work_dir)
"""
import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

from .interface import AbaqusInterface

logger = logging.getLogger(__name__)

# Path to abaqus_scripts/ relative to this file
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "abaqus_scripts"


class RealAbaqusRunner(AbaqusInterface):

    def __init__(self, abaqus_path: str, work_dir: str):
        """
        abaqus_path : full path to abaqus executable
                      Windows: "C:/SIMULIA/Abaqus/Commands/abaqus.bat"
                      Linux:   "/usr/SIMULIA/Commands/abaqus"
        work_dir    : directory for .inp, .odb, .dat outputs
        """
        self.abaqus_path = abaqus_path
        self.work_dir    = work_dir
        os.makedirs(work_dir, exist_ok=True)

    # ── Public interface ───────────────────────────────────────────────────────

    def run_mesh_case1(self, step_file: str, params: dict,
                       geometry_params: dict | None = None) -> dict:
        job_name = f"case1_{uuid.uuid4().hex[:8]}"
        result = self._run_cae_script("mesh_case1.py", {
            "step_file": step_file,
            "params":    params,
            "work_dir":  self.work_dir,
            "job_name":  job_name,
        })
        # Export VTK from the resulting .odb (if solve has run)
        # For mesh-only, just return mesh stats
        return {
            "status":           result.get("status", "success"),
            "element_count":    result.get("element_count", 0),
            "max_aspect_ratio": result.get("max_aspect_ratio", 5.0),
            "min_jacobian":     result.get("min_jacobian", 0.8),
            "vtk_file":         result.get("vtk_file", ""),
            "inp_file":         result.get("inp_file", ""),
            "execution_time":   result.get("execution_time", 0),
        }

    def run_mesh_case2(self, step_file: str, params: dict, cut_planes: list[dict],
                       geometry_params: dict | None = None) -> dict:
        job_name = f"case2_{uuid.uuid4().hex[:8]}"
        result = self._run_cae_script("mesh_case2.py", {
            "step_file":  step_file,
            "params":     params,
            "cut_planes": cut_planes,
            "work_dir":   self.work_dir,
            "job_name":   job_name,
        })
        return {
            "status":           result.get("status", "success"),
            "element_count":    result.get("element_count", 0),
            "max_aspect_ratio": result.get("max_aspect_ratio", 5.0),
            "min_jacobian":     result.get("min_jacobian", 0.75),
            "vtk_file":         result.get("vtk_file", ""),
            "inp_file":         result.get("inp_file", ""),
            "execution_time":   result.get("execution_time", 0),
        }

    def apply_bc(self, inp_file: str, bc_params: dict) -> dict:
        job_name = Path(inp_file).stem + "_bc"
        result   = self._run_cae_script("apply_bc.py", {
            "inp_file":  inp_file,
            "bc_params": bc_params,
            "work_dir":  self.work_dir,
            "job_name":  job_name,
        })
        return {
            "status":        result.get("status", "success"),
            "modified_file": result.get("modified_file", inp_file),
        }

    def submit_job(self, inp_file: str,
                   geometry_params: dict | None = None,
                   bc_params: dict | None = None,
                   case_type: str = "case1",
                   mesh_result: dict | None = None,
                   cut_planes: list[dict] | None = None) -> dict:
        """
        Submit Abaqus analysis job and export VTK with stress colormap.
        Returns same schema as MockAbaqusRunner.submit_job().
        """
        job_name  = Path(inp_file).stem
        odb_file  = os.path.join(self.work_dir, f"{job_name}.odb")
        vtk_file  = os.path.join(self.work_dir, f"{job_name}.vtk")
        allowable = float((bc_params or {}).get("allowable_stress_mpa", 138.0))

        start = time.time()

        # 1. Run Abaqus standard analysis
        logger.info("Submitting Abaqus job: %s", job_name)
        cmd = [
            self.abaqus_path,
            f"job={job_name}",
            f"input={inp_file}",
            "interactive",
            "ask_delete=OFF",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=self.work_dir,
                timeout=7200,   # 2 hour hard limit
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed", "error": "Job timed out after 2 hours"}
        except subprocess.CalledProcessError as e:
            return {"status": "failed", "error": str(e)}

        if not os.path.exists(odb_file):
            return {"status": "failed", "error": f"ODB not found: {odb_file}"}

        # 2. Export VTK + extract summary stats from .odb
        logger.info("Exporting VTK from %s", odb_file)
        vtk_result = self._run_python_script("export_vtk.py", {
            "odb_file": odb_file,
            "vtk_file": vtk_file,
        })

        max_mises = vtk_result.get("max_mises_mpa", 0.0)
        max_disp  = vtk_result.get("max_displacement_mm", 0.0)
        sf = round(allowable / max_mises, 3) if max_mises > 0 else None

        return {
            "status":               "completed",
            "job_name":             job_name,
            "max_mises":            max_mises,
            "max_displacement":     max_disp,
            "max_stress_location":  f"element {vtk_result.get('max_stress_element')}",
            "allowable_stress":     allowable,
            "safety_factor":        sf,
            "sif":                  None,    # computed from actual FEA, not formula
            "pressure_mpa":         float((bc_params or {}).get("pressure_mpa", 10.0)),
            "result_file":          odb_file,
            "vtk_file":             vtk_file,
            "execution_time":       round(time.time() - start, 2),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run_cae_script(self, script_name: str, script_args: dict) -> dict:
        """
        Run an abaqus_scripts/*.py file in Abaqus CAE no-GUI mode.
        The script reads args from args.json and writes results to result.json.
        """
        run_id      = uuid.uuid4().hex[:8]
        args_file   = os.path.join(self.work_dir, f"args_{run_id}.json")
        result_file = os.path.join(self.work_dir, f"result_{run_id}.json")
        script_path = str(_SCRIPTS_DIR / script_name)

        with open(args_file, "w") as f:
            json.dump(script_args, f, indent=2)

        cmd = [
            self.abaqus_path,
            "cae",
            "-noGUI",
            script_path,
            "--",
            args_file,
            result_file,
        ]

        logger.info("Running CAE script: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=self.work_dir,
                timeout=3600,
            )
        finally:
            # Clean up args file
            if os.path.exists(args_file):
                os.remove(args_file)

        if not os.path.exists(result_file):
            raise RuntimeError(f"Script {script_name} did not produce result.json")

        with open(result_file) as f:
            result = json.load(f)

        os.remove(result_file)
        return result

    def _run_python_script(self, script_name: str, script_args: dict) -> dict:
        """
        Run an abaqus_scripts/*.py file using standalone Abaqus Python (not CAE).
        Used for post-processing (.odb parsing) which doesn't need the CAE GUI.
        """
        run_id      = uuid.uuid4().hex[:8]
        args_file   = os.path.join(self.work_dir, f"args_{run_id}.json")
        result_file = os.path.join(self.work_dir, f"result_{run_id}.json")
        script_path = str(_SCRIPTS_DIR / script_name)

        with open(args_file, "w") as f:
            json.dump(script_args, f, indent=2)

        # "abaqus python script.py" runs in standalone Abaqus Python environment
        cmd = [
            self.abaqus_path,
            "python",
            script_path,
            "--",
            args_file,
            result_file,
        ]

        logger.info("Running Abaqus Python script: %s", script_name)
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=self.work_dir,
                timeout=600,
            )
        finally:
            if os.path.exists(args_file):
                os.remove(args_file)

        if not os.path.exists(result_file):
            raise RuntimeError(f"Script {script_name} did not produce result.json")

        with open(result_file) as f:
            result = json.load(f)

        os.remove(result_file)
        return result
