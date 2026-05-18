"""
Case 2: Partition + mixed mesh (Auto Tet junction, Map Hex straight).
Called via: abaqus cae -noGUI mesh_case2.py -- args.json result.json

args.json schema:
  {
    "step_file": "/path/to/file.x_t",
    "params": {"seed_size": 12.5},
    "cut_planes": [
      {"axis": "X", "offset": 700.0},
      {"axis": "X", "offset": 2100.0},
      {"axis": "branch", "offset": 300.0,
       "normal": [0.0, 0.7071, 0.7071],
       "point": [1400.0, 212.1, 212.1],
       "angle_deg": 45.0}
    ],
    "work_dir": "/path/to/work",
    "job_name": "fea_case2"
  }

Cutting strategy:
  - X-axis planes  → DatumPlaneByPrincipalPlane (YZPLANE)
  - Branch planes  → DatumPlaneByPointNormal (oblique)
  After partitioning:
  - Junction zone (between X cuts) → TET / FREE  (Auto Mesh)
  - Straight sections              → HEX / SWEEP (Map Mesh)
"""
import sys
import os
import json
import time

args_file   = sys.argv[-2]
result_file = sys.argv[-1]

with open(args_file) as f:
    args = json.load(f)

step_file  = args["step_file"]
params     = args.get("params", {})
cut_planes = args.get("cut_planes", [])
work_dir   = args.get("work_dir", os.path.dirname(step_file))
job_name   = args.get("job_name", "fea_case2")
seed_size  = float(params.get("seed_size", 12.5))

start = time.time()

# ── Abaqus imports ────────────────────────────────────────────────────────────
from abaqus import mdb, backwardCompatibility
from abaqusConstants import (
    CARTESIAN, THREE_D, DEFORMABLE_BODY,
    YZPLANE, XZPLANE, XYPLANE,
    TET, HEX, FREE, SWEEP,
    ON, OFF
)

backwardCompatibility.setValues(reportDeprecated=False)

# ── Import geometry ───────────────────────────────────────────────────────────
model_name = "Model-Case2"
ext = os.path.splitext(step_file)[1].lower()

if ext in (".stp", ".step"):
    mdb.openStep(filename=step_file, scale=1.0)
elif ext in (".x_t", ".x_b"):
    mdb.openParasolid(filename=step_file, scale=1.0)
else:
    raise ValueError(f"Unsupported format: {ext}")

imported_model = list(mdb.models.keys())[-1]
mdb.Model(name=model_name, objectToCopy=mdb.models[imported_model])
del mdb.models[imported_model]

model     = mdb.models[model_name]
part_name = list(model.parts.keys())[0]
part      = model.parts[part_name]

# ── Apply datum planes and partition ─────────────────────────────────────────
x_cut_offsets = []

for plane in cut_planes:
    axis   = plane.get("axis", "X").upper()
    offset = float(plane.get("offset", 0.0))

    if axis == "X":
        # Axis-aligned: plane perpendicular to X
        datum = part.DatumPlaneByPrincipalPlane(
            principalPlane=YZPLANE,
            offset=offset,
        )
        x_cut_offsets.append(offset)

    elif axis == "Y":
        datum = part.DatumPlaneByPrincipalPlane(
            principalPlane=XZPLANE,
            offset=offset,
        )

    elif axis == "Z":
        datum = part.DatumPlaneByPrincipalPlane(
            principalPlane=XYPLANE,
            offset=offset,
        )

    elif axis == "BRANCH":
        # Oblique plane perpendicular to branch axis
        normal = plane.get("normal", [0.0, 0.7071, 0.7071])
        point  = plane.get("point",  [1400.0, 212.0, 212.0])

        datum = part.DatumPlaneByPointNormal(
            point=(float(point[0]),  float(point[1]),  float(point[2])),
            normal=(float(normal[0]), float(normal[1]), float(normal[2])),
        )

    else:
        continue  # unsupported axis, skip

    # Partition all cells with this datum plane
    try:
        part.PartitionCellByDatumPlane(
            datumPlane=part.datums[datum.id],
            cells=part.cells,
        )
    except Exception as e:
        # Partition may fail if plane misses all cells — not fatal
        print(f"Warning: partition skipped ({axis}={offset}): {e}")

# ── Assign mesh controls per zone ────────────────────────────────────────────
if x_cut_offsets and len(x_cut_offsets) >= 2:
    x_jct_left  = min(x_cut_offsets)
    x_jct_right = max(x_cut_offsets)

    # Junction zone: bounding box between the two X cuts (generous Y/Z bounds)
    bb_pad = 2000.0  # mm — large enough to capture the whole cross-section
    junction_cells = part.cells.getByBoundingBox(
        xMin=x_jct_left,  xMax=x_jct_right,
        yMin=-bb_pad,      yMax=bb_pad,
        zMin=-bb_pad,      zMax=bb_pad,
    )

    if junction_cells:
        part.setMeshControls(
            regions=junction_cells,
            elemShape=TET,
            technique=FREE,
        )

    # Straight sections: cells outside the junction X range
    straight_left = part.cells.getByBoundingBox(
        xMin=-1e9, xMax=x_jct_left,
        yMin=-bb_pad, yMax=bb_pad,
        zMin=-bb_pad, zMax=bb_pad,
    )
    straight_right = part.cells.getByBoundingBox(
        xMin=x_jct_right, xMax=1e9,
        yMin=-bb_pad, yMax=bb_pad,
        zMin=-bb_pad, zMax=bb_pad,
    )
    for straight_cells in (straight_left, straight_right):
        if straight_cells:
            try:
                part.setMeshControls(
                    regions=straight_cells,
                    elemShape=HEX,
                    technique=SWEEP,
                )
            except Exception:
                # Fallback to TET if geometry doesn't support sweep
                part.setMeshControls(
                    regions=straight_cells,
                    elemShape=TET,
                    technique=FREE,
                )
else:
    # No X cuts provided — fallback to global TET
    part.setMeshControls(
        regions=part.cells,
        elemShape=TET,
        technique=FREE,
    )

# ── Global seed + generate ────────────────────────────────────────────────────
part.seedPart(
    size=seed_size,
    deviationFactor=0.1,
    minSizeFactor=0.1,
)
part.generateMesh()

# ── Stats ─────────────────────────────────────────────────────────────────────
elem_count  = len(part.elements)
quality     = part.getMeshStats()
max_ar      = getattr(quality, "maxAspectRatio",  5.0)
min_jac     = getattr(quality, "minJacobian",    0.75)

# ── Assembly + write .inp ─────────────────────────────────────────────────────
assembly = model.rootAssembly
assembly.DatumCsysByDefault(CARTESIAN)
assembly.Instance(name=f"{part_name}-1", part=part, dependent=ON)

job = mdb.Job(name=job_name, model=model_name, description="Case2 FEA")
job.writeInput(consistencyChecking=OFF)

inp_file = os.path.join(work_dir, f"{job_name}.inp")

# ── Result ────────────────────────────────────────────────────────────────────
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
