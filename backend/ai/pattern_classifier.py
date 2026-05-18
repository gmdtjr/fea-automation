"""
Vision-based pipe geometry pattern classifier.
Separates "what shape is this?" from "where to cut?" — clean SRP.
"""
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field

from ai.claude_client import get_client

logger = logging.getLogger(__name__)
MODEL = "claude-sonnet-4-6"

# ── Known pattern registry ────────────────────────────────────────────────────

PATTERNS: dict[str, dict] = {
    "lateral_tee": {
        "description": "비스듬한 분기관 — branch가 45°~75° 각도로 header에 연결",
        "case": 2,
        "needs_branch_cut": True,
        "min_cuts": 4,
    },
    "t_joint_90": {
        "description": "수직 T-분기관 — branch가 header에 90° 수직으로 연결",
        "case": 2,
        "needs_branch_cut": True,
        "min_cuts": 4,
    },
    "y_joint": {
        "description": "Y형 분기관 — branch가 30° 이하 예각으로 연결",
        "case": 2,
        "needs_branch_cut": True,
        "min_cuts": 4,
    },
    "multi_branch": {
        "description": "다중 분기 — branch가 2개 이상",
        "case": 2,
        "needs_branch_cut": True,
        "min_cuts": 6,
    },
    "elbow": {
        "description": "엘보 — 분기 없이 파이프가 굽어지는 형상",
        "case": 1,
        "needs_branch_cut": False,
        "min_cuts": 2,
    },
    "straight_pipe": {
        "description": "직관 — 굴곡/분기 없는 단순 직선 파이프",
        "case": 1,
        "needs_branch_cut": False,
        "min_cuts": 0,
    },
    "unknown": {
        "description": "판별 불가 — 위 패턴에 해당하지 않는 형상",
        "case": None,
        "needs_branch_cut": None,
        "min_cuts": 0,
    },
}

CLASSIFICATION_PROMPT = """당신은 배관 FEA 전문가입니다.
첨부 이미지들은 동일한 배관 형상을 여러 각도에서 렌더링한 것입니다.
형상 파라미터도 참고용으로 제공됩니다 (heuristic 추출이라 부정확할 수 있음).

## 분류 가능한 패턴
- lateral_tee   : 비스듬한 분기관 (branch 각도 30°~75°)
- t_joint_90    : 수직 T-분기관 (branch 각도 약 90°)
- y_joint       : Y형 분기관 (branch 각도 30° 이하 예각)
- multi_branch  : 다중 분기 (branch 2개 이상)
- elbow         : 엘보 (분기 없이 굽어짐)
- straight_pipe : 직관 (굴곡/분기 없음)
- unknown       : 위 패턴에 해당하지 않음

## 판단 기준 (이미지를 우선으로 판단)
1. branch가 있는가? 있다면 몇 개?
2. branch와 header의 각도는 얼마인가? (이미지에서 직접 추정)
3. 파라미터와 이미지 사이 불일치가 있는가?
4. 이상한 점(추가 노즐, 비대칭, 용접부 등)이 있는가?

## 신뢰도 기준
- high   : 이미지와 파라미터 모두 동일 패턴을 명확히 나타냄
- medium : 패턴은 파악되지만 세부 불확실 (각도 애매, 파라미터 불일치 등)
- low    : 판별 어려움 — 수동 검토 필요

## 출력 (JSON만, 마크다운 없이)
{
  "pattern": "<위 목록 중 하나>",
  "confidence": "high/medium/low",
  "observations": "이미지에서 관찰한 내용 1-2문장",
  "branch_angle_deg_estimate": <이미지에서 추정한 각도, 없으면 null>,
  "branch_count": <branch 개수, 없으면 0>,
  "param_discrepancy": "<파라미터와 이미지 불일치 내용, 없으면 null>",
  "anomalies": "<이상 형상 메모, 없으면 null>",
  "case_recommendation": <1 or 2>
}"""


@dataclass
class PatternResult:
    pattern: str
    confidence: str              # "high" | "medium" | "low"
    observations: str
    branch_angle_deg_estimate: float | None = None
    branch_count: int = 0
    param_discrepancy: str | None = None
    anomalies: str | None = None
    case_recommendation: int | None = None
    info: dict = field(default_factory=dict)  # PATTERNS entry

    @property
    def is_known(self) -> bool:
        return self.pattern != "unknown"

    @property
    def needs_human_review(self) -> bool:
        return self.confidence == "low" or not self.is_known


async def classify_pattern(
    geometry_params: dict,
    stl_path: str | None = None,
) -> PatternResult:
    client = get_client()
    content = []

    # Attach screenshots
    if stl_path and os.path.exists(stl_path):
        try:
            from pipeline.geometry_renderer import render_stl_screenshots
            shots = render_stl_screenshots(stl_path, angles=["iso", "front", "top", "side"])
            for img in shots.values():
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(img).decode(),
                    },
                })
            logger.info("Classifier: attached %d screenshots", len(shots))
        except Exception as e:
            logger.warning("Classifier screenshot failed: %s", e)

    # Add params + prompt
    hp = geometry_params.get("header_pipe", {})
    bp = geometry_params.get("branch_pipe", {})
    params_summary = (
        f"Header OD={hp.get('outer_radius',0)*2000:.0f}mm, "
        f"Branch OD={bp.get('outer_radius',0)*2000:.0f}mm, "
        f"branch_angle_deg={bp.get('angle_deg','?')}°"
    )
    content.append({
        "type": "text",
        "text": f"## 참고 파라미터 (heuristic, 부정확할 수 있음)\n{params_summary}\n\n{CLASSIFICATION_PROMPT}",
    })

    response = await client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": content}],
    )

    text = response.content[0].text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        logger.error("Classifier failed to parse: %s", text[:200])
        return _fallback_classify(geometry_params)

    try:
        raw = json.loads(m.group())
    except json.JSONDecodeError:
        return _fallback_classify(geometry_params)

    pattern = raw.get("pattern", "unknown")
    if pattern not in PATTERNS:
        pattern = "unknown"

    result = PatternResult(
        pattern=pattern,
        confidence=raw.get("confidence", "low"),
        observations=raw.get("observations", ""),
        branch_angle_deg_estimate=raw.get("branch_angle_deg_estimate"),
        branch_count=raw.get("branch_count", 0),
        param_discrepancy=raw.get("param_discrepancy"),
        anomalies=raw.get("anomalies"),
        case_recommendation=raw.get("case_recommendation"),
        info=PATTERNS[pattern],
    )
    logger.info("Classified: %s (confidence=%s)", pattern, result.confidence)
    return result


def _fallback_classify(geometry_params: dict) -> PatternResult:
    """Rule-based fallback when Vision fails."""
    bp = geometry_params.get("branch_pipe", {})
    angle = bp.get("angle_deg", 90.0)

    if angle >= 80:
        pattern = "t_joint_90"
    elif 30 <= angle < 80:
        pattern = "lateral_tee"
    elif angle < 30:
        pattern = "y_joint"
    else:
        pattern = "unknown"

    return PatternResult(
        pattern=pattern,
        confidence="medium",
        observations=f"Vision 불가 — 파라미터 기반 분류 (angle_deg={angle}°)",
        branch_angle_deg_estimate=angle,
        info=PATTERNS[pattern],
    )
