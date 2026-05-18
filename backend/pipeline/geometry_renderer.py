"""
Headless STL renderer using matplotlib Agg backend.
No display server (Xvfb) needed — works on ARM64 Docker.
"""
import io
import struct
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

logger = logging.getLogger(__name__)

VIEWS = {
    "iso":   {"elev": 25,  "azim": 45,  "title": "Isometric"},
    "front": {"elev": 0,   "azim": 90,  "title": "Front (Y-Z)"},
    "top":   {"elev": 90,  "azim": -90, "title": "Top (X-Y)"},
    "side":  {"elev": 0,   "azim": 0,   "title": "Side (X-Z)"},
}


def render_stl_screenshots(
    stl_path: str,
    angles: list[str] | None = None,
    cut_planes: list[dict] | None = None,
    geometry_params: dict | None = None,
    dpi: int = 130,
) -> dict[str, bytes]:
    """
    Render binary STL from multiple angles.
    - Overlays junction center marker (red ×) so Claude can reference it
    - Draws OD scale bar so Claude can estimate distances from the image
    - Optionally overlays proposed cut planes
    """
    angles = angles or ["iso", "front", "top", "side"]
    triangles, verts_flat = _parse_stl(stl_path)
    if not triangles:
        return {}

    x_min, x_max = verts_flat[:, 0].min(), verts_flat[:, 0].max()
    y_min, y_max = verts_flat[:, 1].min(), verts_flat[:, 1].max()
    z_min, z_max = verts_flat[:, 2].min(), verts_flat[:, 2].max()
    pad = max(x_max - x_min, y_max - y_min, z_max - z_min) * 0.07

    # Extract annotation data from geometry_params
    jct_x = jct_y = jct_z = 0.0
    header_od = branch_od = None
    if geometry_params:
        jct = geometry_params.get("junction", {})
        ctr = jct.get("center", [0, 0, 0])
        jct_x, jct_y, jct_z = (c * 1000 for c in ctr)
        header_od = geometry_params.get("header_pipe", {}).get("outer_radius", 0) * 2000
        branch_od = geometry_params.get("branch_pipe", {}).get("outer_radius", 0) * 2000

    screenshots = {}
    for angle in angles:
        cfg = VIEWS.get(angle, VIEWS["iso"])
        fig = plt.figure(figsize=(8, 6), facecolor="white")
        ax = fig.add_subplot(111, projection="3d")
        ax.set_facecolor("#f0f4f8")

        # Geometry
        poly = Poly3DCollection(triangles, linewidths=0.05, alpha=0.72)
        poly.set_facecolor("#4488cc")
        poly.set_edgecolor("#223355")
        ax.add_collection3d(poly)

        # Junction center marker (red ×)
        ax.scatter([jct_x], [jct_y], [jct_z],
                   color="red", s=60, marker="x", zorder=10, linewidths=2)
        ax.text(jct_x, jct_y, jct_z + pad * 0.4,
                f"JCT\n({jct_x:.0f},{jct_y:.0f},{jct_z:.0f})",
                fontsize=5.5, color="red", ha="center")

        # OD scale bars (header + branch) along X axis at bottom of plot
        if header_od:
            bar_y = y_min - pad * 0.6
            bar_z = z_min - pad * 0.3
            ax.plot([jct_x - header_od/2, jct_x + header_od/2],
                    [bar_y, bar_y], [bar_z, bar_z],
                    color="#cc3300", linewidth=1.5, alpha=0.8)
            ax.text(jct_x, bar_y, bar_z - pad * 0.3,
                    f"Header OD={header_od:.0f}mm",
                    fontsize=5, color="#cc3300", ha="center")
        if branch_od:
            bar_y2 = y_min - pad * 1.1
            ax.plot([jct_x - branch_od/2, jct_x + branch_od/2],
                    [bar_y2, bar_y2], [bar_z if header_od else z_min, bar_z if header_od else z_min],
                    color="#aa6600", linewidth=1.2, alpha=0.8)
            ax.text(jct_x, bar_y2, (bar_z if header_od else z_min) - pad * 0.3,
                    f"Branch OD={branch_od:.0f}mm",
                    fontsize=5, color="#aa6600", ha="center")

        # Proposed cut planes
        if cut_planes:
            _draw_cut_planes(ax, cut_planes,
                             (x_min, x_max), (y_min, y_max), (z_min, z_max))

        ax.set_xlim(x_min - pad, x_max + pad)
        ax.set_ylim(y_min - pad * 1.5, y_max + pad)
        ax.set_zlim(z_min - pad * 0.5, z_max + pad)
        ax.set_xlabel("X (mm)", fontsize=7)
        ax.set_ylabel("Y (mm)", fontsize=7)
        ax.set_zlabel("Z (mm)", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_title(f"{cfg['title']}  |  JCT=({jct_x:.0f}, {jct_y:.0f}, {jct_z:.0f})",
                     fontsize=8, pad=4)
        ax.view_init(elev=cfg["elev"], azim=cfg["azim"])

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        screenshots[angle] = buf.read()

    return screenshots


# ──────────────────────────────────────────────────────────────────────────────

def _parse_stl(path: str):
    try:
        with open(path, "rb") as f:
            data = f.read()
        n_tri = struct.unpack_from("<I", data, 80)[0]
        triangles = []
        offset = 84
        for _ in range(n_tri):
            offset += 12  # skip normal
            v0 = struct.unpack_from("<3f", data, offset); offset += 12
            v1 = struct.unpack_from("<3f", data, offset); offset += 12
            v2 = struct.unpack_from("<3f", data, offset); offset += 12
            offset += 2
            triangles.append([v0, v1, v2])
        verts_flat = np.array(triangles).reshape(-1, 3)
        return triangles, verts_flat
    except Exception as e:
        logger.warning("STL parse failed: %s", e)
        return [], np.zeros((0, 3))


def _draw_cut_planes(ax, cut_planes, x_range, y_range, z_range):
    colours = ["#ff4444", "#ff8800", "#22cc88"]
    x0, x1 = x_range; y0, y1 = y_range; z0, z1 = z_range

    for i, cp in enumerate(cut_planes):
        colour = colours[i % len(colours)]
        axis   = cp.get("axis", "X").upper()
        offset = float(cp.get("offset", 0))

        if axis == "X":
            ys = np.array([y0, y1, y1, y0])
            zs = np.array([z0, z0, z1, z1])
            xs = np.full(4, offset)
        elif axis == "Y":
            xs = np.array([x0, x1, x1, x0])
            zs = np.array([z0, z0, z1, z1])
            ys = np.full(4, offset)
        else:  # Z
            xs = np.array([x0, x1, x1, x0])
            ys = np.array([y0, y0, y1, y1])
            zs = np.full(4, offset)

        verts = [list(zip(xs, ys, zs))]
        plane = Poly3DCollection(verts, alpha=0.30)
        plane.set_facecolor(colour)
        plane.set_edgecolor(colour)
        ax.add_collection3d(plane)
        # Label
        ax.text(xs.mean(), ys.mean(), zs.mean(),
                f"{axis}={offset:.0f}", color=colour, fontsize=6, ha="center")
