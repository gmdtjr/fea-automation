"""
Export geometry as surface STL for 3D viewer.
Uses Gmsh if available, otherwise builds a synthetic Lateral Tee from params.
"""
import math
import os
import struct
from typing import List, Tuple

Vec3 = Tuple[float, float, float]
Triangle = Tuple[Vec3, Vec3, Vec3]


def export_surface_stl(file_path: str, geometry_params: dict, output_path: str) -> str:
    try:
        import gmsh
        _export_with_gmsh(file_path, output_path)
    except (ImportError, Exception):
        _synthetic_lateral_tee_stl(geometry_params, output_path)
    return output_path


# ---------------------------------------------------------------------------
# Gmsh path (x86_64)
# ---------------------------------------------------------------------------

def _export_with_gmsh(file_path: str, output_path: str) -> None:
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Verbosity", 0)
        gmsh.merge(file_path)
        gmsh.model.occ.synchronize()
        # Surface mesh only (dim=2)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", 30.0)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 5.0)
        gmsh.model.mesh.generate(2)
        stl_path = output_path if output_path.endswith(".stl") else output_path + ".stl"
        gmsh.write(stl_path)
    finally:
        gmsh.finalize()


# ---------------------------------------------------------------------------
# Synthetic Lateral Tee fallback
# ---------------------------------------------------------------------------

def _synthetic_lateral_tee_stl(geometry_params: dict, output_path: str) -> None:
    hp  = geometry_params.get("header_pipe", {})
    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    bb  = geometry_params.get("bounding_box", {})

    header_r   = hp.get("outer_radius", 0.432) * 1000   # m → mm
    header_len = hp.get("length", 2.8) * 1000
    branch_r   = bp.get("outer_radius", 0.216) * 1000
    angle_deg  = bp.get("angle_deg", 45.0)
    angle_rad  = math.radians(angle_deg)
    jct_center = [c * 1000 for c in jct.get("center", [1.4, 0.0, 0.0])]

    # Branch axis unit vector (branch rises in +Y/+Z plane)
    bx = 0.0
    by = math.cos(angle_rad)
    bz = math.sin(angle_rad)

    # Branch length from bounding_box (more accurate than OD × constant)
    branch_len = _branch_len_from_bbox(bb, by, bz, branch_r)

    triangles: List[Triangle] = []

    # ── Header: centered at junction along X ──────────────────────────────────
    triangles += _cylinder(
        center=(jct_center[0], jct_center[1], jct_center[2]),
        axis=(1, 0, 0),
        radius=header_r,
        length=header_len,
        segments=48,
    )

    # ── Branch: starts AT junction, extends OUTWARD only ─────────────────────
    # Center = junction + (branch_len/2) * branch_axis  → starts at junction, ends at tip
    branch_center = (
        jct_center[0] + bx * branch_len / 2,
        jct_center[1] + by * branch_len / 2,
        jct_center[2] + bz * branch_len / 2,
    )
    triangles += _cylinder(
        center=branch_center,
        axis=(bx, by, bz),
        radius=branch_r,
        length=branch_len,
        segments=36,
    )

    _write_binary_stl(output_path, triangles)


def _branch_len_from_bbox(bb: dict, by: float, bz: float, branch_r: float) -> float:
    """
    Estimate branch pipe length from bounding_box extents.
    bb values are in metres; returns mm.
    Falls back to branch_r × 6 if bbox unavailable.
    """
    z_raw = (bb.get("z") or [None, None])[1]
    y_raw = (bb.get("y") or [None, None])[1]

    # Detect unit: if values look like metres (≤ 10), convert to mm
    def to_mm(v: float | None) -> float:
        if v is None: return 0.0
        return abs(v) * 1000 if abs(v) <= 10 else abs(v)

    z_max_mm = to_mm(z_raw)
    y_max_mm = to_mm(y_raw)

    # Estimate branch length from each axis independently, take the maximum
    estimates = []
    if abs(bz) > 0.01 and z_max_mm > branch_r:
        estimates.append(z_max_mm / abs(bz))
    if abs(by) > 0.01 and y_max_mm > branch_r:
        estimates.append(y_max_mm / abs(by))

    if not estimates:
        return branch_r * 6

    return max(max(estimates), branch_r * 3)


def _cylinder(
    center: Tuple[float, float, float],
    axis: Tuple[float, float, float],
    radius: float,
    length: float,
    segments: int,
) -> List[Triangle]:
    """Generate triangles for a solid cylinder."""
    ax, ay, az = _normalize(axis)

    # Build perpendicular basis vectors
    if abs(ax) < 0.9:
        perp = _normalize(_cross((ax, ay, az), (1, 0, 0)))
    else:
        perp = _normalize(_cross((ax, ay, az), (0, 1, 0)))
    perp2 = _cross((ax, ay, az), perp)

    cx, cy, cz = center
    half = length / 2

    def ring(t: float) -> List[Vec3]:
        points = []
        for i in range(segments):
            theta = 2 * math.pi * i / segments
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            rx = perp[0] * cos_t + perp2[0] * sin_t
            ry = perp[1] * cos_t + perp2[1] * sin_t
            rz = perp[2] * cos_t + perp2[2] * sin_t
            points.append((
                cx + ax * t + rx * radius,
                cy + ay * t + ry * radius,
                cz + az * t + rz * radius,
            ))
        return points

    r1 = ring(-half)
    r2 = ring(+half)
    tris: List[Triangle] = []

    # Side faces
    for i in range(segments):
        j = (i + 1) % segments
        tris.append((r1[i], r2[i], r2[j]))
        tris.append((r1[i], r2[j], r1[j]))

    # End caps (fan triangulation)
    cap1 = (cx - ax * half, cy - ay * half, cz - az * half)
    cap2 = (cx + ax * half, cy + ay * half, cz + az * half)
    for i in range(segments):
        j = (i + 1) % segments
        tris.append((cap1, r1[j], r1[i]))
        tris.append((cap2, r2[i], r2[j]))

    return tris


def _write_binary_stl(path: str, triangles: List[Triangle]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * 80)                        # header
        f.write(struct.pack("<I", len(triangles)))    # triangle count
        for v0, v1, v2 in triangles:
            n = _triangle_normal(v0, v1, v2)
            f.write(struct.pack("<3f", *n))
            f.write(struct.pack("<3f", *v0))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<H", 0))             # attribute byte count


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z = v
    mag = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / mag, y / mag, z / mag)


def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _triangle_normal(v0: Vec3, v1: Vec3, v2: Vec3) -> Vec3:
    ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
    return _normalize((
        ay * bz - az * by,
        az * bx - ax * bz,
        ax * by - ay * bx,
    ))
