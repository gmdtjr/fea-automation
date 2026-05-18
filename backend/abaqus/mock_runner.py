import os
import time
import math
import numpy as np

from .interface import AbaqusInterface

try:
    import gmsh
    _GMSH_AVAILABLE = True
except ImportError:
    _GMSH_AVAILABLE = False


class MockAbaqusRunner(AbaqusInterface):
    """
    Gmsh-based mock runner for development without Abaqus.
    Falls back to a synthetic VTK cylinder mesh when gmsh is unavailable
    (e.g., ARM64 Linux Docker).
    """

    def __init__(self, output_dir: str = "./output_dir"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_mesh_case1(self, step_file: str, params: dict,
                       geometry_params: dict | None = None) -> dict:
        vtk_file = self._vtk_path(step_file, "case1")
        start = time.time()

        if _GMSH_AVAILABLE:
            elem_count, max_ar = self._gmsh_mesh(step_file, params, vtk_file, cut_planes=[])
        else:
            elem_count, max_ar = self._synthetic_mesh(vtk_file, params,
                                                      geometry_params=geometry_params)

        return {
            "status": "success",
            "element_count": elem_count,
            "max_aspect_ratio": max_ar,
            "min_jacobian": 0.85,
            "vtk_file": vtk_file,
            "execution_time": round(time.time() - start, 2),
        }

    def run_mesh_case2(self, step_file: str, params: dict, cut_planes: list[dict],
                       geometry_params: dict | None = None) -> dict:
        vtk_file = self._vtk_path(step_file, "case2")
        start = time.time()

        if _GMSH_AVAILABLE:
            elem_count, max_ar = self._gmsh_mesh(step_file, params, vtk_file, cut_planes)
        else:
            elem_count, max_ar = self._synthetic_mesh(vtk_file, params,
                                                      geometry_params=geometry_params,
                                                      cut_planes=cut_planes)

        return {
            "status": "success",
            "element_count": elem_count,
            "max_aspect_ratio": max_ar,
            "min_jacobian": 0.82,
            "vtk_file": vtk_file,
            "execution_time": round(time.time() - start, 2),
        }

    def apply_bc(self, inp_file: str, bc_params: dict) -> dict:
        return {"status": "success", "modified_file": inp_file}

    def submit_job(
        self, inp_file: str,
        geometry_params: dict | None = None,
        bc_params: dict | None = None,
        case_type: str = "case1",
        mesh_result: dict | None = None,
        cut_planes: list[dict] | None = None,
    ) -> dict:
        job_name = os.path.splitext(os.path.basename(inp_file))[0]
        result = _estimate_stress(
            geometry_params or {}, bc_params or {},
            case_type=case_type,
            mesh_result=mesh_result,
            cut_planes=cut_planes,
        )
        return {
            "status": "completed",
            "job_name": job_name,
            "result_file": inp_file.replace(".inp", ".dat"),
            **result,
        }

    # ------------------------------------------------------------------
    # Internal: gmsh path (x86_64)
    # ------------------------------------------------------------------

    def _gmsh_mesh(self, step_file: str, params: dict, vtk_file: str, cut_planes: list[dict]):
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Verbosity", 0)
            gmsh.merge(step_file)
            gmsh.model.occ.synchronize()

            if cut_planes:
                volumes = gmsh.model.occ.getEntities(3)
                for plane in cut_planes:
                    cb = _gmsh_cut_box(plane)
                    if cb is not None and volumes:
                        gmsh.model.occ.fragment([(3, v[1]) for v in volumes], [(3, cb)])
                        gmsh.model.occ.synchronize()

            seed_size = params.get("seed_size", 5.0)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", seed_size)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", seed_size / 10)
            gmsh.option.setNumber("Mesh.Algorithm3D", 4)
            gmsh.option.setNumber("Mesh.Optimize", 1)
            gmsh.model.mesh.generate(3)
            gmsh.write(vtk_file)

            elem_tags = gmsh.model.mesh.getElementsByType(4)[1]
            if len(elem_tags) > 0:
                qualities = gmsh.model.mesh.getElementQualities(elem_tags, "aspectRatio")
                return len(qualities), float(np.max(qualities))
            return 0, 1.0
        finally:
            gmsh.finalize()

    # ------------------------------------------------------------------
    # Internal: synthetic VTK fallback (ARM64 / no gmsh)
    # ------------------------------------------------------------------

    def _synthetic_mesh(self, vtk_file: str, params: dict,
                        geometry_params: dict | None = None,
                        cut_planes: list[dict] | None = None):
        """
        Generate a surface quad mesh of the actual pipe geometry (Lateral Tee or straight).
        Uses geometry_params for correct shape. Much smaller than volumetric mesh.
        Includes CELL_DATA region scalars for color-coding.

        Region codes:
          0 = header Map Mesh zone (blue)
          1 = junction Auto Mesh zone (orange)
          2 = branch Auto Mesh zone ① (pink, between cut① and cut②)
          3 = branch Map Mesh zone (teal, beyond cut②)
        """
        geo = geometry_params or {}
        hp = geo.get("header_pipe", {})
        bp = geo.get("branch_pipe", {})
        jct = geo.get("junction", {})

        h_outer_r  = hp.get("outer_radius", 0.432) * 1000   # mm
        h_length   = hp.get("length", 2.8) * 1000
        b_outer_r  = bp.get("outer_radius", 0.216) * 1000
        angle_deg  = bp.get("angle_deg", 45.0)
        jct_center = [c * 1000 for c in jct.get("center", [1.4, 0.0, 0.0])]
        jct_x, jct_y, jct_z = jct_center

        seed_size  = params.get("seed_size", 25.0)
        angle_rad  = math.radians(angle_deg)

        # Branch length from bounding_box (same logic as geometry_exporter)
        from pipeline.geometry_exporter import _branch_len_from_bbox
        bb = geo.get("bounding_box", {})
        bx_v, by_v = 0.0, math.cos(angle_rad)
        bz_v = math.sin(angle_rad)
        b_length = _branch_len_from_bbox(bb, by_v, bz_v, b_outer_r)

        # Mesh density from seed_size, then scale to ≤30k total quads for browser performance
        n_circ_h  = max(16, int(2 * math.pi * h_outer_r / seed_size))
        n_axial_h = max(8,  int(h_length / seed_size))
        n_circ_b  = max(12, int(2 * math.pi * b_outer_r / seed_size))
        n_axial_b = max(8,  int(b_length / seed_size))

        estimated = n_circ_h * n_axial_h + n_circ_b * n_axial_b
        if estimated > 30_000:
            scale = math.sqrt(30_000 / estimated)
            n_circ_h  = max(16, int(n_circ_h  * scale))
            n_axial_h = max(8,  int(n_axial_h * scale))
            n_circ_b  = max(12, int(n_circ_b  * scale))
            n_axial_b = max(8,  int(n_axial_b * scale))

        # Header cut boundaries
        header_cut_dist = 1.5 * h_outer_r * 2  # approx junction zone half-width
        x_jct_left  = jct_x - header_cut_dist
        x_jct_right = jct_x + header_cut_dist
        # Branch cut boundaries
        b_cut_bottom = 0.5 * b_outer_r * 2
        b_cut_top    = 1.5 * b_outer_r * 2

        # Override with actual approved cut planes if provided
        if cut_planes:
            x_cuts = sorted(p["offset"] for p in cut_planes if p.get("axis") == "X")
            b_cuts = sorted(p.get("offset", 0) for p in cut_planes if p.get("axis") == "branch")
            if len(x_cuts) >= 2:
                x_jct_left, x_jct_right = x_cuts[0], x_cuts[-1]
            if len(b_cuts) >= 2:
                b_cut_bottom, b_cut_top = b_cuts[0], b_cuts[-1]

        # Branch axis and perpendicular bases
        bx, by, bz = 0.0, math.cos(angle_rad), math.sin(angle_rad)
        # Perp to branch: use X axis (works since bx=0)
        p1x, p1y, p1z = 1.0, 0.0, 0.0
        # Second perp: cross(branch, p1)
        p2x = by * p1z - bz * p1y
        p2y = bz * p1x - bx * p1z
        p2z = bx * p1y - by * p1x
        p2len = math.sqrt(p2x*p2x + p2y*p2y + p2z*p2z)
        p2x, p2y, p2z = p2x/p2len, p2y/p2len, p2z/p2len

        all_pts: list[tuple[float, float, float]] = []
        all_cells: list[list[int]] = []   # each = list of 4 vertex indices (quad)
        all_regions: list[int] = []

        def add_pt(x, y, z) -> int:
            all_pts.append((round(x, 2), round(y, 2), round(z, 2)))
            return len(all_pts) - 1

        # ── Header outer surface (cylinder, outer radius) ──────────────────
        h_start = jct_x - h_length / 2
        h_ring_pts: list[list[int]] = []
        for i_ax in range(n_axial_h + 1):
            x = h_start + h_length * i_ax / n_axial_h
            ring = []
            for i_c in range(n_circ_h):
                theta = 2 * math.pi * i_c / n_circ_h
                y = jct_y + h_outer_r * math.cos(theta)
                z = jct_z + h_outer_r * math.sin(theta)
                ring.append(add_pt(x, y, z))
            h_ring_pts.append(ring)

        for i_ax in range(n_axial_h):
            x_mid = h_start + h_length * (i_ax + 0.5) / n_axial_h
            if cut_planes:
                # Case 2: show junction Auto(Tet) zone in orange
                region = 1 if x_jct_left <= x_mid <= x_jct_right else 0
            else:
                # Case 1: uniform Hex/Map throughout — all blue, no partitioning
                region = 0
            for i_c in range(n_circ_h):
                j = (i_c + 1) % n_circ_h
                all_cells.append([h_ring_pts[i_ax][i_c], h_ring_pts[i_ax][j],
                                   h_ring_pts[i_ax+1][j], h_ring_pts[i_ax+1][i_c]])
                all_regions.append(region)

        # ── Header wall end caps (annular rings at both ends) ────────────────
        for x_end in [h_start, h_start + h_length]:
            n_rad = max(2, int((h_outer_r * 0.13) / seed_size))  # wall thickness divisions
            inner_r = h_outer_r * 0.88  # approximate inner radius
            for i_r in range(n_rad):
                r0 = inner_r + (h_outer_r - inner_r) * i_r / n_rad
                r1 = inner_r + (h_outer_r - inner_r) * (i_r + 1) / n_rad
                for i_c in range(n_circ_h):
                    theta0 = 2 * math.pi * i_c / n_circ_h
                    theta1 = 2 * math.pi * (i_c + 1) / n_circ_h
                    p0 = add_pt(x_end, jct_y + r0 * math.cos(theta0), jct_z + r0 * math.sin(theta0))
                    p1 = add_pt(x_end, jct_y + r1 * math.cos(theta0), jct_z + r1 * math.sin(theta0))
                    p2 = add_pt(x_end, jct_y + r1 * math.cos(theta1), jct_z + r1 * math.sin(theta1))
                    p3 = add_pt(x_end, jct_y + r0 * math.cos(theta1), jct_z + r0 * math.sin(theta1))
                    all_cells.append([p0, p1, p2, p3])
                    all_regions.append(0)

        # ── Branch outer surface (cylinder along branch axis) ────────────────
        b_ring_pts: list[list[int]] = []
        for i_ax in range(n_axial_b + 1):
            dist = b_length * i_ax / n_axial_b
            cx = jct_x + bx * dist
            cy = jct_y + by * dist
            cz = jct_z + bz * dist
            ring = []
            for i_c in range(n_circ_b):
                theta = 2 * math.pi * i_c / n_circ_b
                cos_t, sin_t = math.cos(theta), math.sin(theta)
                px = cx + b_outer_r * (cos_t * p1x + sin_t * p2x)
                py = cy + b_outer_r * (cos_t * p1y + sin_t * p2y)
                pz = cz + b_outer_r * (cos_t * p1z + sin_t * p2z)
                ring.append(add_pt(px, py, pz))
            b_ring_pts.append(ring)

        for i_ax in range(n_axial_b):
            dist_mid = b_length * (i_ax + 0.5) / n_axial_b
            if not cut_planes:
                # Case 1: branch도 균일 Hex — 전체 파란색
                region = 0
            elif dist_mid < b_cut_bottom:
                region = 1  # junction zone (Auto Tet)
            elif dist_mid < b_cut_top:
                region = 2  # branch Auto Tet (cut① ~ cut②)
            else:
                region = 3  # branch Map Hex (cut② 이후)
            for i_c in range(n_circ_b):
                j = (i_c + 1) % n_circ_b
                all_cells.append([b_ring_pts[i_ax][i_c], b_ring_pts[i_ax][j],
                                   b_ring_pts[i_ax+1][j], b_ring_pts[i_ax+1][i_c]])
                all_regions.append(region)

        # ── Branch wall end cap ───────────────────────────────────────────────
        n_rad_b = max(2, int((b_outer_r * 0.13) / seed_size))
        inner_r_b = b_outer_r * 0.88
        dist_end = b_length
        cx = jct_x + bx * dist_end
        cy = jct_y + by * dist_end
        cz = jct_z + bz * dist_end
        for i_r in range(n_rad_b):
            r0 = inner_r_b + (b_outer_r - inner_r_b) * i_r / n_rad_b
            r1 = inner_r_b + (b_outer_r - inner_r_b) * (i_r + 1) / n_rad_b
            for i_c in range(n_circ_b):
                theta0 = 2 * math.pi * i_c / n_circ_b
                theta1 = 2 * math.pi * (i_c + 1) / n_circ_b
                def bpt(r, theta):
                    cos_t, sin_t = math.cos(theta), math.sin(theta)
                    return add_pt(
                        cx + r * (cos_t * p1x + sin_t * p2x),
                        cy + r * (cos_t * p1y + sin_t * p2y),
                        cz + r * (cos_t * p1z + sin_t * p2z),
                    )
                all_cells.append([bpt(r0, theta0), bpt(r1, theta0),
                                   bpt(r1, theta1), bpt(r0, theta1)])
                all_regions.append(3)

        _write_lateral_tee_vtk(vtk_file, all_pts, all_cells, all_regions)
        elem_count = len(all_cells)
        max_ar = 2.5 + (seed_size / 20.0)
        return elem_count, round(max_ar, 3)

    def _vtk_path(self, step_file: str, suffix: str) -> str:
        base = os.path.splitext(os.path.basename(step_file))[0]
        return os.path.join(self.output_dir, f"{base}_{suffix}.vtk")


def _write_lateral_tee_vtk(path: str, points: list, cells: list, regions: list) -> None:
    """
    Write VTK ASCII unstructured grid with quad elements and region CELL_DATA.
    Region: 0=header(Map/Hex), 1=junction(Auto/Tet), 2=branch_auto, 3=branch_map
    """
    n_pts   = len(points)
    n_cells = len(cells)
    cell_list_size = sum(len(c) + 1 for c in cells)  # +1 for count prefix

    with open(path, "w") as f:
        f.write("# vtk DataFile Version 2.0\n")
        f.write("FEA Mock Surface Mesh - Lateral Tee\n")
        f.write("ASCII\n")
        f.write("DATASET UNSTRUCTURED_GRID\n")
        f.write(f"POINTS {n_pts} float\n")
        for p in points:
            f.write(f"{p[0]} {p[1]} {p[2]}\n")

        f.write(f"\nCELLS {n_cells} {cell_list_size}\n")
        for c in cells:
            f.write(f"{len(c)} " + " ".join(map(str, c)) + "\n")

        f.write(f"\nCELL_TYPES {n_cells}\n")
        for c in cells:
            f.write("9\n" if len(c) == 4 else "5\n")  # 9=QUAD, 5=TRIANGLE

        f.write(f"\nCELL_DATA {n_cells}\n")
        f.write("SCALARS region int 1\n")
        f.write("LOOKUP_TABLE default\n")
        for r in regions:
            f.write(f"{r}\n")


def _gmsh_cut_box(plane: dict):
    """
    Return a Gmsh volume tag that can be used to fragment (cut) the geometry.
    Supports axis-aligned planes and branch-perpendicular oblique planes.
    """
    import gmsh
    import math as _math

    axis = plane.get("axis", "X").upper()
    box_size = 5000.0

    if axis in ("X", "Y", "Z"):
        offset = float(plane.get("offset", 0.0))
        if axis == "X":
            return gmsh.model.occ.addBox(offset, -box_size / 2, -box_size / 2, box_size, box_size, box_size)
        elif axis == "Y":
            return gmsh.model.occ.addBox(-box_size / 2, offset, -box_size / 2, box_size, box_size, box_size)
        else:
            return gmsh.model.occ.addBox(-box_size / 2, -box_size / 2, offset, box_size, box_size, box_size)

    if axis == "BRANCH":
        # Oblique plane: add a large box, then rotate it so its face aligns with the branch normal
        normal = plane.get("normal", [0, 1, 0])
        point  = plane.get("point",  [0, 0, 0])
        nx, ny, nz = normal

        # Box starts at the plane point, extends far in the half-space of the normal
        cb = gmsh.model.occ.addBox(
            point[0] - box_size / 2,
            point[1] - box_size / 2,
            point[2] - box_size / 2,
            box_size, box_size, box_size,
        )

        # Rotate so box face aligns with the branch plane
        # Branch normal = (nx, ny, nz). We want the box cut face to be ⊥ to normal.
        # Default box face is along Z. Compute rotation angle from Z to normal.
        default = (0.0, 0.0, 1.0)
        # Rotation axis = cross(default, normal)
        rx = default[1] * nz - default[2] * ny
        ry = default[2] * nx - default[0] * nz
        rz = default[0] * ny - default[1] * nx
        r_len = _math.sqrt(rx*rx + ry*ry + rz*rz)
        if r_len > 1e-9:
            angle = _math.acos(max(-1.0, min(1.0, nx*default[0] + ny*default[1] + nz*default[2])))
            gmsh.model.occ.rotate(
                [(3, cb)],
                point[0], point[1], point[2],
                rx / r_len, ry / r_len, rz / r_len,
                angle,
            )
        return cb

    return None


# ---------------------------------------------------------------------------
# Engineering formula-based stress estimation (thin-wall pressure vessel)
# ---------------------------------------------------------------------------

def _estimate_stress(
    geometry_params: dict,
    bc_params: dict,
    case_type: str = "case1",
    mesh_result: dict | None = None,
    cut_planes: list[dict] | None = None,
) -> dict:
    """
    Estimate max Von Mises stress and displacement for a pressurised pipe/tee
    using thin-wall (Lamé) theory + empirical stress concentration factors.

    Assumptions:
    - Internal pressure loading only (conservative lower bound)
    - Material: carbon steel (E=200 GPa, ν=0.3)
    - Stress concentration at branch junction (SIF per ASME B31.3 Appendix D)
    """
    import math

    # --- Geometry ---
    hp = geometry_params.get("header_pipe", {})
    bp = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})

    r_o = hp.get("outer_radius", 0.432) * 1000   # mm
    r_i = hp.get("inner_radius", 0.382) * 1000   # mm
    t = r_o - r_i                                  # wall thickness, mm
    r_m = (r_o + r_i) / 2                          # mean radius, mm

    br_o = bp.get("outer_radius", 0.216) * 1000
    br_i = bp.get("inner_radius", 0.191) * 1000
    bt = br_o - br_i
    br_m = (br_o + br_i) / 2

    angle_deg = bp.get("angle_deg", 90.0)
    fillet_r = jct.get("fillet_radius", 0.0) * 1000  # mm

    # --- Loading ---
    pressure = float(bc_params.get("pressure_mpa", 10.0))   # MPa

    # --- Material ---
    E = float(bc_params.get("youngs_modulus_mpa", 200_000))  # MPa
    nu = 0.3
    allowable = float(bc_params.get("allowable_stress_mpa", 138.0))  # A106 Gr.B

    # --- Base hoop stress (thin-wall) ---
    sigma_hoop_header = pressure * r_m / t
    sigma_hoop_branch = pressure * br_m / bt if bt > 0 else sigma_hoop_header

    # --- Stress Intensity Factor at branch junction (simplified ASME B31.3) ---
    beta = br_o / r_o                            # branch-to-header diameter ratio
    angle_rad = math.radians(angle_deg)
    angle_factor = 1.0 / math.sin(angle_rad) if angle_rad > 0 else 2.0
    fillet_factor = max(0.6, 1.0 - fillet_r / (2 * t)) if t > 0 else 1.0
    sif_base = max(1.0, (0.9 / (beta ** 0.5)) * angle_factor * fillet_factor)
    sif_base = min(sif_base, 5.0)

    # ── Case differentiation: mesh approach affects junction stress capture accuracy ──
    #
    # Physical model:
    #   Case 1 (uniform mesh, no partition):
    #     Junction is NOT isolated → elements span the complex transition zone
    #     → Mesh smearing underestimates local peak stress
    #     → Result: LOWER stress, but LESS ACCURATE (non-conservative)
    #
    #   Case 2 (partitioned mesh):
    #     Junction zone isolated → Tet elements fill only the complex region
    #     Straight sections use structured Hex → accurate far-field stress
    #     → Better resolution of actual stress concentration
    #     → Result: HIGHER stress, MORE ACCURATE
    #     → The closer the cuts to the junction, the more precisely
    #        the Tet zone covers the real complexity → higher captured stress

    if case_type == "case2" and cut_planes:
        # Evaluate how tightly the cuts bracket the junction
        jct_x_mm = jct.get("center", [0, 0, 0])[0] * 1000
        x_cuts = sorted(p["offset"] for p in cut_planes if p.get("axis") == "X")

        if len(x_cuts) >= 2:
            # Distance from junction to nearest header cut (mm)
            header_cut_dist = min(abs(x - jct_x_mm) for x in x_cuts)
            # Optimal = 1×header_OD. Closer cuts → tighter junction zone → better resolution
            optimal_dist = r_o * 2              # 1×header_OD
            # capture_ratio: 1.0 at optimal, >1 if cuts are closer (even better), <1 if cuts are farther
            capture_ratio = max(0.5, min(2.0, optimal_dist / header_cut_dist))
        else:
            capture_ratio = 0.8  # no cuts info

        # Branch cuts: having both bottom and top cuts further refines the branch zone
        b_cuts = [p["offset"] for p in cut_planes if p.get("axis") == "branch"]
        branch_bonus = 0.05 if len(b_cuts) >= 2 else 0.0

        # Case 2 captures sif_base × junction_capture_factor
        # junction_capture_factor ranges 1.1 – 1.35 (better than Case 1 which misses stress)
        junction_capture = 1.10 + 0.20 * (capture_ratio - 0.5) + branch_bonus
        junction_capture = min(1.40, max(1.05, junction_capture))

        sif       = round(sif_base * junction_capture, 3)
        mesh_note = (f"Case 2 (partition, cuts at {header_cut_dist:.0f}mm from junction, "
                     f"capture_factor={junction_capture:.2f})")
    else:
        # Case 1: junction NOT isolated → mesh smearing → under-estimates peak stress
        # Captured stress ≈ 75–85% of true junction stress concentration
        smear_factor = 0.80
        sif       = round(sif_base * smear_factor, 3)
        mesh_note = "Case 1 (uniform mesh, junction stress under-estimated ~20%)"

    sif = min(sif, 5.0)

    max_mises = round(sigma_hoop_header * sif, 1)

    if sif > 1.0:
        stress_loc = f"branch-header junction ({mesh_note})"
    else:
        stress_loc = "header mid-span (hoop)"

    # --- Max displacement ---
    delta_r_header = pressure * r_m ** 2 / (E * t)
    max_disp = round(delta_r_header * sif * 0.6, 3)

    return {
        "max_mises": max_mises,
        "max_displacement": max_disp,
        "max_stress_location": stress_loc,
        "allowable_stress": allowable,
        "safety_factor": round(allowable / max_mises, 3) if max_mises > 0 else None,
        "sif": sif,
        "sif_analytical": round(sif_base, 3),
        "sigma_hoop_header_mpa": round(sigma_hoop_header, 1),
        "sigma_hoop_branch_mpa": round(sigma_hoop_branch, 1),
        "pressure_mpa": pressure,
        "mesh_max_aspect_ratio": round((mesh_result or {}).get("max_aspect_ratio", 0), 3),
        "case_type": case_type,
    }
