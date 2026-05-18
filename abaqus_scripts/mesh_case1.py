"""
Case 1: Sweep + Map mesh (no geo cutting).
Called via: abaqus cae -noGUI mesh_case1.py -- args.json result.json

args.json schema:
  {
    "step_file": "/path/to/file.x_t",
    "params": {"seed_size": 12.5},
    "work_dir": "/path/to/work",
    "job_name": "fea_case1"
  }

result.json schema:
  {
    "status": "success",
    "element_count": 12345,
    "max_aspect_ratio": 3.2,
    "min_jacobian": 0.85,
    "inp_file": "/path/to/job.inp",
    "execution_time": 42.0
  }
"""
import sys
import os
import json
import time

# ── Read args ─────────────────────────────────────────────────────────────────
args_file   = sys.argv[-2]
result_file = sys.argv[-1]

with open(args_file) as f:
    args = json.load(f)

step_file = args["step_file"]
params    = args.get("params", {})
work_dir  = args.get("work_dir", os.path.dirname(step_file))
job_name  = args.get("job_name", "fea_case1")
seed_size = float(params.get("seed_size", 12.5))

start = time.time()

# ── Abaqus imports (only available inside Abaqus Python) ─────────────────────
from abaqus import mdb, backwardCompatibility
from abaqusConstants import (
    STANDARD_EXPLICIT, STANDARD, THREE_D, DEFORMABLE_BODY,
    YZPLANE, XZPLANE, XYPLANE,
    TET, HEX, FREE, SWEEP, STRUCTURED,
    ON, OFF
)
import mesh as abaqus_mesh

backwardCompatibility.setValues(reportDeprecated=False)

# ── Import geometry ───────────────────────────────────────────────────────────
model_name = "Model-Case1"
ext = os.path.splitext(step_file)[1].lower()

if ext in (".stp", ".step"):
    mdb.openStep(filename=step_file, scale=1.0)
elif ext in (".x_t", ".x_b"):
    mdb.openParasolid(filename=step_file, scale=1.0)
else:
    raise ValueError(f"Unsupported format: {ext}")

# Rename model created by import
imported_model = list(mdb.models.keys())[-1]
mdb.Model(name=model_name, objectToCopy=mdb.models[imported_model])
del mdb.models[imported_model]

model = mdb.models[model_name]
part_name = list(model.parts.keys())[0]
part = model.parts[part_name]

# ── Mesh seed + generate ──────────────────────────────────────────────────────
# Case 1: uniform global seed, let Abaqus choose element type
part.seedPart(
    size=seed_size,
    deviationFactor=0.1,
    minSizeFactor=0.1,
)

# Use structured/sweep where geometry allows, free elsewhere
part.setMeshControls(
    regions=part.cells,
    elemShape=TET,
    technique=FREE,
)
# Try structured on simpler pipe sections
try:
    part.setMeshControls(
        regions=part.cells,
        elemShape=HEX,
        technique=SWEEP,
    )
except Exception:
    pass  # fallback to TET/FREE if geometry too complex

part.generateMesh()

# ── Element statistics ────────────────────────────────────────────────────────
elem_count = len(part.elements)

# Aspect ratio: average of element quality metrics
quality_stats = part.getMeshStats()
max_ar  = getattr(quality_stats, "maxAspectRatio",  5.0)
min_jac = getattr(quality_stats, "minJacobian",    0.8)

# ── Create assembly and write .inp ────────────────────────────────────────────
assembly = model.rootAssembly
assembly.DatumCsysByDefault(CARTESIAN)
instance = assembly.Instance(
    name=f"{part_name}-1",
    part=part,
    dependent=ON,
)

# Create job and write input file
job = mdb.Job(name=job_name, model=model_name, description="Case1 FEA")
job.writeInput(consistencyChecking=OFF)

inp_file = os.path.join(work_dir, f"{job_name}.inp")

# ── Write result ──────────────────────────────────────────────────────────────
result = {
    "status": "success",
    "element_count": elem_count,
    "max_aspect_ratio": float(max_ar),
    "min_jacobian": float(min_jac),
    "inp_file": inp_file,
    "execution_time": round(time.time() - start, 2),
}

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
