import json
from ai.claude_client import get_client

MODEL = "claude-sonnet-4-6"


async def analyze_results(result_data: dict, geometry_params: dict) -> str:
    client = get_client()

    prompt = f"""당신은 배관 FEA 해석 전문가입니다.
해석 결과를 엔지니어링 관점에서 해석하고 요약하세요.

## 형상 정보
{json.dumps(geometry_params, indent=2, ensure_ascii=False)}

## 해석 결과
최대 Von Mises 응력: {result_data.get('max_mises', 'N/A')} MPa
최대 변위: {result_data.get('max_displacement', 'N/A')} mm
최대 응력 발생 위치: {result_data.get('max_stress_location', 'N/A')}
재료 허용 응력: {result_data.get('allowable_stress', 250)} MPa

## 출력 형식
- 안전율 계산 및 판정 (OK / NG)
- 최대 응력 발생 부위 설명
- 주의사항 또는 개선 권고 (있으면)
- 3줄 요약"""

    response = await client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
