"""
Export .odb results to VTK ASCII with stress colormap.
Called via: abaqus python export_vtk.py -- args.json result.json
(uses standalone Abaqus Python, not CAE GUI mode)

args.json schema:
  {
    "odb_file": "/path/to/job.odb",
    "vtk_file": "/path/to/output.vtk",
    "step_name": "Step-1",          # optional, default last step
    "frame_index": -1               # optional, -1 = last frame
  }

Output VTK includes:
  - POINTS (node coordinates)
  - CELLS  (element connectivity, Tet4→type10, Tet10→type24, Hex8→type12)
  - CELL_DATA: SCALARS mises (Von Mises stress per element)
  - POINT_DATA: SCALARS displacement_mag (displacement magnitude per node)
"""
import sys
import os
import json
import time

args_file   = sys.argv[-2]
result_file = sys.argv[-1]

with open(args_file) as f:
    args = json.load(f)

odb_file    = args["odb_file"]
vtk_file    = args["vtk_file"]
step_name   = args.get("step_name",   None)    # None → last step
frame_index = args.get("frame_index", -1)

start = time.time()

# ── Abaqus ODB API ────────────────────────────────────────────────────────────
from odbAccess import openOdb
from abaqusConstants import MISES, MAGNITUDE, NODAL, CENTROID

odb      = openOdb(path=odb_file, readOnly=True)
step     = odb.steps[step_name] if step_name else list(odb.steps.values())[-1]
frame    = step.frames[frame_index]
instance = list(odb.rootAssembly.instances.values())[0]

# ── Extract mesh ──────────────────────────────────────────────────────────────
nodes    = instance.nodes
elements = instance.elements

# Node coordinates: {label: (x, y, z)}
node_coords = {n.label: n.coordinates for n in nodes}

# Sorted node labels for 0-based indexing
sorted_node_labels = sorted(node_coords.keys())
node_index = {label: i for i, label in enumerate(sorted_node_labels)}

# ── Extract field outputs ─────────────────────────────────────────────────────
# Von Mises stress (element centroid)
S_field  = frame.fieldOutputs.get("S", None)
mises_by_elem = {}
if S_field:
    S_mises = S_field.getScalarField(invariant=MISES)
    for val in S_mises.values:
        mises_by_elem[val.elementLabel] = val.data

# Displacement magnitude (nodal)
U_field  = frame.fieldOutputs.get("U", None)
disp_by_node = {}
if U_field:
    U_mag = U_field.getScalarField(invariant=MAGNITUDE)
    for val in U_mag.values:
        disp_by_node[val.nodeLabel] = val.data

# ── VTK element type mapping ──────────────────────────────────────────────────
# Abaqus element type → VTK cell type
VTK_TYPE = {
    "C3D4":  10,  # Tet4
    "C3D10": 24,  # Tet10  (quadratic)
    "C3D8":  12,  # Hex8
    "C3D8R": 12,  # Hex8 reduced integration
    "C3D20": 25,  # Hex20 (quadratic)
    "C3D6":  13,  # Wedge6
}

# ── Write VTK ─────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(vtk_file), exist_ok=True)

with open(vtk_file, "w") as f:
    # Header
    f.write("# vtk DataFile Version 2.0\n")
    f.write(f"Abaqus FEA Result — {os.path.basename(odb_file)}\n")
    f.write("ASCII\n")
    f.write("DATASET UNSTRUCTURED_GRID\n")

    # Points
    f.write(f"\nPOINTS {len(sorted_node_labels)} float\n")
    for label in sorted_node_labels:
        x, y, z = node_coords[label]
        f.write(f"{x:.6f} {y:.6f} {z:.6f}\n")

    # Cells
    valid_elements = []
    for elem in elements:
        conn = elem.connectivity       # list of node labels
        vtk_t = VTK_TYPE.get(elem.type, 10)  # default Tet4
        valid_elements.append((elem.label, conn, vtk_t))

    cell_list_size = sum(1 + len(c) for _, c, _ in valid_elements)
    f.write(f"\nCELLS {len(valid_elements)} {cell_list_size}\n")
    for _, conn, _ in valid_elements:
        indices = [node_index[n] for n in conn if n in node_index]
        f.write(f"{len(indices)} " + " ".join(map(str, indices)) + "\n")

    f.write(f"\nCELL_TYPES {len(valid_elements)}\n")
    for _, _, vtk_t in valid_elements:
        f.write(f"{vtk_t}\n")

    # Cell data: Von Mises stress
    f.write(f"\nCELL_DATA {len(valid_elements)}\n")
    f.write("SCALARS mises float 1\n")
    f.write("LOOKUP_TABLE default\n")
    for elem_label, _, _ in valid_elements:
        f.write(f"{mises_by_elem.get(elem_label, 0.0):.4f}\n")

    # Point data: displacement magnitude
    f.write(f"\nPOINT_DATA {len(sorted_node_labels)}\n")
    f.write("SCALARS displacement_mag float 1\n")
    f.write("LOOKUP_TABLE default\n")
    for label in sorted_node_labels:
        f.write(f"{disp_by_node.get(label, 0.0):.6f}\n")

odb.close()

# ── Compute summary stats ─────────────────────────────────────────────────────
max_mises = max(mises_by_elem.values()) if mises_by_elem else 0.0
max_disp  = max(disp_by_node.values())  if disp_by_node  else 0.0

# Location of max stress: find element label
max_mises_elem = max(mises_by_elem, key=mises_by_elem.get) if mises_by_elem else None

result = {
    "status": "success",
    "vtk_file": vtk_file,
    "element_count": len(valid_elements),
    "node_count": len(sorted_node_labels),
    "max_mises_mpa": float(max_mises),
    "max_displacement_mm": float(max_disp),
    "max_stress_element": int(max_mises_elem) if max_mises_elem else None,
    "step_name": step.name,
    "frame_description": frame.description,
    "execution_time": round(time.time() - start, 2),
}

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
