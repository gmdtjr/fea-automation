"""
Hybrid cut advisor — Vision-primary approach.

Step 1: Vision classifies the pattern AND visually estimates the complexity zone
        (how far the complex geometry extends from the junction in the images)
Step 2: Vision directly proposes cut positions based on what it sees
        Rules are referenced as guidelines, NOT forced constraints
Step 3: Post-process: bounding box clamp + missing branch cut guard

Key design decision:
  - AI sees the images and decides where to cut based on actual geometry
  - Rules (1.5×OD etc.) are shown as "typical starting point" in the prompt,
    but AI can and should deviate when the geometry warrants it
  - Low-confidence / unknown patterns → empty cuts → force human review
"""
import base64
import json
import logging
import math
import os
import re
from datetime import datetime

from ai.claude_client import get_client
from ai.pattern_classifier import PATTERNS

logger = logging.getLogger(__name__)
MODEL = "claude-sonnet-4-6"


# ─── Public entry point ───────────────────────────────────────────────────────

async def suggest_cut_position(
    geometry_params: dict,
    stl_path: str | None = None,
) -> dict:
    client  = get_client()
    content = []

    # Render annotated screenshots (junction marker + OD scale bar)
    if stl_path and os.path.exists(stl_path):
        try:
            from pipeline.geometry_renderer import render_stl_screenshots
            shots = render_stl_screenshots(
                stl_path,
                angles=["iso", "front", "top", "side"],
                geometry_params=geometry_params,
            )
            for img in shots.values():
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(img).decode(),
                    },
                })
            logger.info("Attached %d annotated screenshots", len(shots))
        except Exception as e:
            logger.warning("Screenshot failed (%s) — text-only", e)

    content.append({"type": "text", "text": _build_prompt(geometry_params)})

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1400,
        messages=[{"role": "user", "content": content}],
    )

    text = response.content[0].text
    raw = _extract_json(text)
    if raw is None:
        logger.error("Failed to parse AI response: %s", text[:300])
        return rule_based_fallback(geometry_params)

    pattern = raw.get("pattern", "unknown")
    if pattern not in PATTERNS:
        pattern = "unknown"

    cut_planes = raw.get("cut_planes", [])
    confidence = raw.get("confidence", "medium")
    needs_review = (confidence == "low" or pattern == "unknown")

    # Post-process
    cut_planes = _postprocess(cut_planes, geometry_params, pattern)

    return {
        "cut_planes": cut_planes,
        "confidence": confidence,
        "warning": raw.get("warning"),
        "observations": raw.get("observations"),
        "visual_analysis": raw.get("visual_analysis"),
        "pattern": pattern,
        "pattern_description": PATTERNS.get(pattern, {}).get("description", ""),
        "branch_angle_estimate": raw.get("branch_angle_estimate"),
        "param_discrepancy": raw.get("param_discrepancy"),
        "anomalies": raw.get("anomalies"),
        "needs_human_review": needs_review,
    }


# ─── Prompt ───────────────────────────────────────────────────────────────────

def _build_prompt(geometry_params: dict) -> str:
    hp  = geometry_params.get("header_pipe", {})
    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    bb  = geometry_params.get("bounding_box", {})

    header_od = hp.get("outer_radius", 0) * 2000
    branch_od = bp.get("outer_radius", 0) * 2000
    angle_deg = bp.get("angle_deg", 90.0)
    fillet_r  = jct.get("fillet_radius", 0) * 1000
    ctr       = [c * 1000 for c in jct.get("center", [0, 0, 0])]
    jct_x, jct_y, jct_z = ctr

    angle_rad = math.radians(angle_deg)
    nx, ny, nz = 0.0, math.cos(angle_rad), math.sin(angle_rad)

    # Rule-based reference values (shown as guideline, not requirement)
    ref_base = 1.5 * header_od
    if fillet_r > header_od / 4: ref_base *= 1.2
    if angle_deg < 45: ref_base += 0.5 * branch_od
    ref_x_left  = round(jct_x - ref_base, 0)
    ref_x_right = round(jct_x + ref_base, 0)
    ref_b_bottom = round(0.5 * branch_od, 0)
    ref_b_top    = round(1.5 * branch_od, 0)

    bb_str = (f"X:[{bb.get('x',[None,None])[0]}, {bb.get('x',[None,None])[1]}]  "
              f"Y:[{bb.get('y',[None,None])[0]}, {bb.get('y',[None,None])[1]}]  "
              f"Z:[{bb.get('z',[None,None])[0]}, {bb.get('z',[None,None])[1]}]")

    return f"""당신은 FEA 배관 메시 전문가입니다.
첨부 이미지는 동일한 배관 형상을 여러 각도에서 렌더링한 것입니다.
이미지에는 junction 중심(빨간 ×)과 OD 스케일바가 표시되어 있습니다.

## 참고 파라미터 (heuristic 추출 — 이미지로 검증 필요)
- Header OD: {header_od:.0f}mm  (반경 {header_od/2:.0f}mm)
- Branch OD: {branch_od:.0f}mm  (반경 {branch_od/2:.0f}mm)
- Branch 각도: {angle_deg:.1f}° (header X축 기준)
- Branch 축 방향벡터: ({nx:.3f}, {ny:.3f}, {nz:.3f})
- Junction 중심: X={jct_x:.0f}, Y={jct_y:.0f}, Z={jct_z:.0f} mm
- Fillet 반경: {fillet_r:.0f}mm
- Bounding Box: {bb_str}

## 커팅 목적
Junction 주변 복잡 영역 → Auto Mesh (Tet)   [pink 영역]
나머지 직관 구간 → Map Mesh (Hex)            [blue 영역]
경계가 파이프 축에 수직이어야 메시 전환이 깔끔합니다.

## 참고 규칙 (시작점, 이미지 보고 조정하세요)
Header 양쪽: junction ± {ref_base:.0f}mm → X={ref_x_left:.0f} / X={ref_x_right:.0f}
Branch 하단①: junction에서 {ref_b_bottom:.0f}mm (branch_OD×0.5)
Branch 상단②: junction에서 {ref_b_top:.0f}mm (branch_OD×1.5)

## 이미지에서 직접 판단해야 할 것

1. **형상 패턴**: 어떤 종류인가? (lateral_tee / t_joint_90 / y_joint / elbow / straight_pipe / unknown)

2. **복잡 구간 범위**: 이미지에서 junction 곡면이 실제로 얼마나 뻗어 있는가?
   - 빨간 × (junction 중심)에서 header 방향으로 복잡 구간이 몇 mm까지 이어지는가?
   - Branch 방향으로는 몇 mm까지인가?
   - 이미지의 스케일바와 축 눈금을 참고해서 추정하세요.

3. **규칙과의 차이**: 참고 규칙({ref_base:.0f}mm)이 적절한가?
   - fillet이 크거나 접합부 형상이 복잡하면 더 멀리 잘라야 함
   - junction이 단순하면 더 가깝게 잘라도 됨

## 출력 (JSON만, 마크다운 없이, reason은 한 줄)
{{
  "pattern": "lateral_tee",
  "observations": "이미지에서 관찰한 형상 특징 1-2문장",
  "visual_analysis": {{
    "header_complexity_extent_mm": "junction으로부터 header 방향으로 복잡 구간이 끝나는 지점 추정",
    "branch_complexity_extent_mm": "junction으로부터 branch 방향으로 복잡 구간이 끝나는 지점 추정",
    "rule_vs_visual": "참고 규칙({ref_base:.0f}mm)과 이미지 관찰 비교 — 조정이 필요하면 이유 설명"
  }},
  "cut_planes": [
    {{"axis":"X","offset":<mm>,"reason":"header 좌측: 이미지 관찰 기반 — <근거>"}},
    {{"axis":"X","offset":<mm>,"reason":"header 우측: 이미지 관찰 기반 — <근거>"}},
    {{"axis":"branch","offset":<mm>,"normal":[{nx:.4f},{ny:.4f},{nz:.4f}],"point":[<x>,<y>,<z>],"angle_deg":{angle_deg:.1f},"reason":"branch 하단①: <근거>"}},
    {{"axis":"branch","offset":<mm>,"normal":[{nx:.4f},{ny:.4f},{nz:.4f}],"point":[<x>,<y>,<z>],"angle_deg":{angle_deg:.1f},"reason":"branch 상단②: <근거>"}}
  ],
  "branch_angle_estimate": <이미지에서 추정한 각도>,
  "param_discrepancy": "<파라미터와 이미지 불일치, 없으면 null>",
  "anomalies": "<이상 형상, 없으면 null>",
  "confidence": "high/medium/low",
  "warning": null
}}

※ branch 타입 cut_plane의 point = junction + normal × offset:
  [{jct_x:.0f}+{nx:.3f}×offset, {jct_y:.0f}+{ny:.3f}×offset, {jct_z:.0f}+{nz:.3f}×offset]
※ 이미지 관찰 기반으로 참고 규칙에서 벗어나도 됩니다.
※ 중요: JSON의 모든 문자열 값은 반드시 한 줄(single line)로 작성하세요. 줄바꿈 금지."""


# ─── Rule-based fallback ──────────────────────────────────────────────────────

def rule_based_fallback(geometry_params: dict) -> dict:
    """Claude API 미연결 시 순수 rule-based 계산."""
    from ai.cut_rules import compute_cuts
    from ai.pattern_classifier import _fallback_classify

    classification = _fallback_classify(geometry_params)
    cut_planes = compute_cuts(classification.pattern, geometry_params)
    cut_planes = _postprocess(cut_planes, geometry_params, classification.pattern)

    return {
        "cut_planes": cut_planes,
        "confidence": "medium",
        "warning": "Claude API 미연결 — 규칙 기반 자동 계산값. 검토 후 승인하세요.",
        "observations": classification.observations,
        "pattern": classification.pattern,
        "pattern_description": PATTERNS.get(classification.pattern, {}).get("description", ""),
        "needs_human_review": False,
    }


# ─── JSON extraction ─────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """
    Robustly extract the first JSON object from Claude's response.
    Handles:
    - Multi-line string values (actual newlines inside JSON strings)
    - Markdown code fences
    - Trailing commas
    """
    # Remove markdown fences if present
    text = re.sub(r"```(?:json)?\s*", "", text)

    # Find the outermost { ... }
    start = text.find("{")
    if start == -1:
        return None

    # Walk to find matching closing brace
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        return None

    candidate = text[start:end]

    # Replace actual (unescaped) newlines inside JSON string values with space
    # Strategy: collapse whitespace sequences inside string values
    candidate = _collapse_string_newlines(candidate)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: remove trailing commas before ] or }
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            logger.error("JSON parse failed after cleanup: %s | snippet: %s", e, candidate[:200])
            return None


def _collapse_string_newlines(text: str) -> str:
    """Replace literal newlines inside JSON string values with a single space."""
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\":
            result.append(ch)
            escape_next = True
        elif ch == '"' and not escape_next:
            in_string = not in_string
            result.append(ch)
        elif in_string and ch in ("\n", "\r"):
            result.append(" ")
        else:
            result.append(ch)
    return "".join(result)


# ─── Post-processing ──────────────────────────────────────────────────────────

def _postprocess(planes: list[dict], geometry_params: dict, pattern: str) -> list[dict]:
    """
    1. Clamp axis-aligned offsets to bounding box
    2. Fill missing normal/point on branch planes
    3. Guard: tee patterns must have 2 branch planes
    """
    bb     = geometry_params.get("bounding_box", {})
    limits = {
        "X": bb.get("x", [None, None]),
        "Y": bb.get("y", [None, None]),
        "Z": bb.get("z", [None, None]),
    }

    out: list[dict] = []
    branch_planes: list[dict] = []

    for p in planes:
        axis = p.get("axis", "")
        if axis == "branch":
            p = _fill_branch_plane(p, geometry_params)
            branch_planes.append(p)
            out.append(p)
        elif axis in limits:
            lo, hi = limits[axis]
            if lo is not None and p.get("offset", 0) < lo:
                p = {**p, "offset": lo,
                     "reason": p.get("reason","") + f" [BB클램프 {axis}≥{lo}]"}
            if hi is not None and p.get("offset", 0) > hi:
                p = {**p, "offset": hi,
                     "reason": p.get("reason","") + f" [BB클램프 {axis}≤{hi}]"}
            out.append(p)

    # Guard: tee patterns need exactly 2 branch planes
    needs_branch = PATTERNS.get(pattern, {}).get("needs_branch_cut", False)
    if needs_branch:
        if len(branch_planes) == 0:
            logger.warning("AI returned no branch cuts for %s — adding rule-based pair", pattern)
            for p in _rule_branch_planes(geometry_params):
                p["reason"] = p.get("reason","") + " (AI 누락 자동 보완)"
                out.append(p)
        elif len(branch_planes) == 1:
            logger.warning("AI returned 1 branch cut for %s — adding missing one", pattern)
            existing = branch_planes[0]["offset"]
            branch_od = geometry_params.get("branch_pipe", {}).get("outer_radius", 0.216) * 2000
            for p in _rule_branch_planes(geometry_params):
                if abs(p["offset"] - existing) > branch_od * 0.3:
                    p["reason"] = p.get("reason","") + " (누락 보완)"
                    out.append(p)
                    break

    return out


def _fill_branch_plane(plane: dict, geometry_params: dict) -> dict:
    if "normal" in plane and "point" in plane:
        return plane
    bp  = geometry_params.get("branch_pipe", {})
    jct = geometry_params.get("junction", {})
    angle_deg = bp.get("angle_deg", 45.0)
    ctr = [c * 1000 for c in jct.get("center", [0, 0, 0])]
    r = math.radians(angle_deg)
    nx, ny, nz = 0.0, math.cos(r), math.sin(r)
    dist = plane.get("offset", 0)
    point = [round(ctr[0]+nx*dist,1), round(ctr[1]+ny*dist,1), round(ctr[2]+nz*dist,1)]
    return {**plane,
            "normal": [round(nx,4), round(ny,4), round(nz,4)],
            "point": point,
            "angle_deg": angle_deg}


def _rule_branch_planes(geometry_params: dict) -> list[dict]:
    from ai.cut_rules import _branch_plane
    return [
        _branch_plane(geometry_params, 0.5, "하단① (guard)"),
        _branch_plane(geometry_params, 1.5, "상단② (guard)"),
    ]


# ─── DB persistence ──────────────────────────────────────────────────────────

async def save_cut_suggestion(
    job_id: str, geometry_params: dict, suggestion: dict, db
) -> None:
    from db.models import CutSuggestion
    import uuid
    db.add(CutSuggestion(
        id=str(uuid.uuid4()),
        job_id=job_id,
        geometry_params=geometry_params,
        ai_suggestion=suggestion,
        confidence=suggestion.get("confidence"),
        created_at=datetime.utcnow(),
    ))
    db.commit()
