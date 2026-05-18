"""
Pattern-specific rule sets for cut plane computation.
Each function is deterministic given geometry_params.
Vision classifies the pattern; these rules compute the positions.
"""
import math
from typing import Callable


# ── Type alias ───────────────────────────────────────────────────────────────

CutPlane = dict   # { axis, offset, normal?, point?, angle_deg?, reason }
RuleFunc = Callable[[dict], list[CutPlane]]


# ── Shared helpers ────────────────────────────────────────────────────────────

def _branch_axis(angle_deg: float) -> tuple[float, float, float]:
    r = math.radians(angle_deg)
    return (0.0, math.cos(r), math.sin(r))


def _branch_plane(geometry_params: dict, dist_factor: float, label: str) -> CutPlane:
    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    branch_od = bp.get("outer_radius", 0.216) * 2000
    angle_deg = bp.get("angle_deg", 45.0)
    ctr = [c * 1000 for c in jct.get("center", [0, 0, 0])]
    nx, ny, nz = _branch_axis(angle_deg)
    dist  = dist_factor * branch_od
    point = [round(ctr[0]+nx*dist,1), round(ctr[1]+ny*dist,1), round(ctr[2]+nz*dist,1)]
    return {
        "axis": "branch",
        "offset": round(dist, 1),
        "normal": [round(nx,4), round(ny,4), round(nz,4)],
        "point": point,
        "angle_deg": angle_deg,
        "reason": f"branch {label}: junction + normal×{dist:.0f} = {point}",
    }


def _header_x_cuts(geometry_params: dict) -> tuple[float, float, list[str]]:
    """Return (x_left, x_right, steps) after applying all corrections."""
    hp  = geometry_params.get("header_pipe", {})
    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    bb  = geometry_params.get("bounding_box", {})

    header_od = hp.get("outer_radius", 0.432) * 2000
    branch_od = bp.get("outer_radius", 0.216) * 2000
    fillet_r  = jct.get("fillet_radius", 0) * 1000
    angle_deg = bp.get("angle_deg", 45.0)
    jct_x     = jct.get("center", [1.4, 0.0, 0.0])[0] * 1000
    bb_x      = bb.get("x", [None, None])

    base = 1.5 * header_od
    steps = [f"header_OD {header_od:.0f} × 1.5 = {base:.0f}"]

    if fillet_r > header_od / 4:
        c = base * 0.2
        base += c
        steps.append(f"fillet 보정 +{c:.0f}")
    if angle_deg < 45.0:
        c = 0.5 * branch_od
        base += c
        steps.append(f"각도 보정 +{c:.0f}")

    x_l = round(jct_x - base, 1)
    x_r = round(jct_x + base, 1)
    if bb_x[0] is not None: x_l = max(x_l, bb_x[0])
    if bb_x[1] is not None: x_r = min(x_r, bb_x[1])
    return x_l, x_r, steps, jct_x


# ── Rule sets by pattern ──────────────────────────────────────────────────────

def lateral_tee_rules(geometry_params: dict) -> list[CutPlane]:
    """
    4 cuts: X×2 (header) + branch-perpendicular×2 (oblique)
    ① branch bottom = OD×0.5  ② branch top = OD×1.5
    """
    x_l, x_r, steps, jct_x = _header_x_cuts(geometry_params)
    step_str = " + ".join(steps)
    return [
        {"axis": "X", "offset": x_l,
         "reason": f"header 좌측: jct {jct_x:.0f} - ({step_str}) = {x_l}"},
        {"axis": "X", "offset": x_r,
         "reason": f"header 우측: jct {jct_x:.0f} + ({step_str}) = {x_r}"},
        _branch_plane(geometry_params, 0.5, "하단①"),
        _branch_plane(geometry_params, 1.5, "상단②"),
    ]


def t_joint_90_rules(geometry_params: dict) -> list[CutPlane]:
    """
    4 cuts: X×2 (header) + Y or Z axis×2 (branch — axis-aligned since 90°)
    Branch at 90° → normal is axis-aligned, use standard axis plane.
    """
    x_l, x_r, steps, jct_x = _header_x_cuts(geometry_params)
    step_str = " + ".join(steps)

    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    branch_od = bp.get("outer_radius", 0.216) * 2000
    ctr = [c * 1000 for c in jct.get("center", [0.0, 0.0, 0.0])]
    bb  = geometry_params.get("bounding_box", {})

    # For 90° branch, determine dominant axis from bounding box
    y_span = abs((bb.get("y", [-1, 1])[1]) - (bb.get("y", [-1, 1])[0]))
    z_span = abs((bb.get("z", [-1, 1])[1]) - (bb.get("z", [-1, 1])[0]))
    b_axis = "Z" if z_span > y_span else "Y"
    b_jct  = ctr[2] if b_axis == "Z" else ctr[1]

    b_bottom = round(b_jct + 0.5 * branch_od, 1)
    b_top    = round(b_jct + 1.5 * branch_od, 1)

    return [
        {"axis": "X", "offset": x_l,
         "reason": f"header 좌측: jct {jct_x:.0f} - ({step_str}) = {x_l}"},
        {"axis": "X", "offset": x_r,
         "reason": f"header 우측: jct {jct_x:.0f} + ({step_str}) = {x_r}"},
        {"axis": b_axis, "offset": b_bottom,
         "reason": f"branch 하단①: jct {b_axis}={b_jct:.0f} + OD×0.5={0.5*branch_od:.0f} = {b_bottom}"},
        {"axis": b_axis, "offset": b_top,
         "reason": f"branch 상단②: jct {b_axis}={b_jct:.0f} + OD×1.5={1.5*branch_od:.0f} = {b_top}"},
    ]


def y_joint_rules(geometry_params: dict) -> list[CutPlane]:
    """
    Y형 분기 — lateral_tee와 동일 방식, angle 보정 적용됨.
    """
    return lateral_tee_rules(geometry_params)


def elbow_rules(geometry_params: dict) -> list[CutPlane]:
    """
    엘보 — Case 1: 굽힘부 양쪽에 X 커팅 2개 (단순 분리).
    branch_cut 없음.
    """
    hp  = geometry_params.get("header_pipe", {})
    jct = geometry_params.get("junction", {})
    bb  = geometry_params.get("bounding_box", {})

    header_od = hp.get("outer_radius", 0.432) * 2000
    jct_x     = jct.get("center", [1.4, 0.0, 0.0])[0] * 1000
    base      = 1.5 * header_od
    bb_x      = bb.get("x", [None, None])

    x_l = round(jct_x - base, 1)
    x_r = round(jct_x + base, 1)
    if bb_x[0] is not None: x_l = max(x_l, bb_x[0])
    if bb_x[1] is not None: x_r = min(x_r, bb_x[1])

    return [
        {"axis": "X", "offset": x_l,
         "reason": f"엘보 좌측: jct {jct_x:.0f} - OD×1.5={base:.0f} = {x_l}"},
        {"axis": "X", "offset": x_r,
         "reason": f"엘보 우측: jct {jct_x:.0f} + OD×1.5={base:.0f} = {x_r}"},
    ]


def straight_pipe_rules(geometry_params: dict) -> list[CutPlane]:
    """직관 — Case 1: 커팅 불필요."""
    return []


def multi_branch_rules(geometry_params: dict) -> list[CutPlane]:
    """
    다중 분기 — 기본 lateral_tee 규칙 적용 + confidence:medium 경고.
    실제로는 각 branch마다 추가 커팅이 필요하나, 파라미터가 1 branch만 담아서 한계 있음.
    """
    return lateral_tee_rules(geometry_params)


# ── Dispatch table ────────────────────────────────────────────────────────────

RULE_SETS: dict[str, RuleFunc] = {
    "lateral_tee":  lateral_tee_rules,
    "t_joint_90":   t_joint_90_rules,
    "y_joint":      y_joint_rules,
    "elbow":        elbow_rules,
    "straight_pipe": straight_pipe_rules,
    "multi_branch": multi_branch_rules,
    "unknown":      lambda _: [],
}


def compute_cuts(pattern: str, geometry_params: dict) -> list[CutPlane]:
    """Dispatch to the appropriate rule function."""
    fn = RULE_SETS.get(pattern, RULE_SETS["unknown"])
    return fn(geometry_params)
