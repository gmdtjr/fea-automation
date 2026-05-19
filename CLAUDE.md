# FEA Automation System — CLAUDE.md

Claude Code 핸드오프 문서. 이 파일을 먼저 읽고 모든 구현을 시작할 것.

---

## 프로젝트 개요

SolidWorks(STEP / Parasolid X_T) → Abaqus 메시 생성 → 해석까지
파이프라인을 자동화하는 시스템.

핵심 설계 원칙:
- Abaqus 없는 PC에서도 개발/테스트 가능 (MockRunner + synthetic mesh)
- 커팅 위치는 Vision-primary AI가 제안 → 사람이 3D 뷰어에서 검토/수정/승인 (Human-in-the-loop)
- AI는 꼭 필요한 곳에만 (영역 인식, 커팅 제안, 결과 해석)
- 나머지는 규칙 기반 또는 Abaqus 코드로 처리
- Abaqus Python Scripting API가 자동화의 핵심 (MIDAS 대체 이유: MIDAS는 API 없음)

---

## 기술 스택

```
Backend    : FastAPI + Python 3.11
DB         : PostgreSQL + SQLAlchemy 2.0
Queue      : Redis + Celery (비동기 태스크)
Frontend   : React + TypeScript + Vite + Tailwind CSS
3D 뷰어    : Three.js (STL 렌더링 + oblique cut planes + 메시 surface viz)
AI         : claude-sonnet-4-20250514 (Anthropic SDK)
형상 파싱   : pythonOCC (STEP) / heuristic fallback (X_T, ARM64)
형상 렌더   : pipeline/geometry_exporter.py → Binary STL
Vision 렌더 : pipeline/geometry_renderer.py (matplotlib Agg, headless, junction 마커 + OD 스케일바)
Mock 메시   : synthetic surface quad mesh (ARM64; x86_64에서는 Gmsh 사용 가능)
실제 메시   : Abaqus Python Scripting API (Phase 2)
컨테이너   : Docker Compose
```

---

## 프로젝트 구조

```
fea-automation/
├── CLAUDE.md
├── docker-compose.yml              # 포트: backend=8001, frontend=5174, db=5433, redis=6380
├── .env / .env.example
│
├── backend/
│   ├── main.py                     # FastAPI + file_watcher 시작
│   ├── config.py                   # pydantic-settings
│   ├── deps.py                     # get_abaqus_runner()
│   ├── worker.py                   # Celery worker (parse_geometry / run_mesh / run_solve 태스크)
│   │                                # run_solve: asyncio.run(analyze_results(...)) 허용
│   │                                # (worker는 별도 프로세스 — anyio 충돌 없음)
│   │
│   ├── pipeline/
│   │   ├── orchestrator.py         # 파이프라인 흐름 (최대 5회 재시도)
│   │   ├── file_watcher.py         # watchdog (watch_dir 감시)
│   │   ├── geometry_parser.py      # STEP/X_T 파라미터 추출 (pythonOCC + heuristic)
│   │   ├── geometry_exporter.py    # X_T → Binary STL (3D 뷰어용)
│   │   │                            # ARM64 fallback: _synthetic_lateral_tee_stl()
│   │   │                            # branch 길이: bounding_box 기반 (_branch_len_from_bbox)
│   │   ├── geometry_renderer.py    # STL → PNG 스크린샷 (Claude Vision용, matplotlib Agg)
│   │   │                            # junction 중심 빨간 × 마커 + OD 스케일바 오버레이
│   │   ├── quality_checker.py      # 메시 품질 규칙 엔진 (Rule-based)
│   │   ├── report_generator.py     # 해석 결과 리포트 생성
│   │   ├── topology_graph.py       # ★ Phase 3: OpenCASCADE 기반 위상 그래프
│   │   └── feature_extractor.py    # ★ Phase 3: 패턴 인식 (Tee/Elbow/Vessel)
│   │
│   ├── abaqus/
│   │   ├── interface.py            # AbaqusInterface 추상 클래스
│   │   │                            # run_mesh_case1/2(step_file, params, geometry_params)
│   │   │                            # submit_job(inp_file, geometry_params, bc_params,
│   │   │                            #            case_type, mesh_result, cut_planes)
│   │   ├── mock_runner.py          # synthetic surface quad mesh (ARM64)
│   │   │                            # _synthetic_mesh(): seed_size 기반 밀도, 30k 상한
│   │   │                            # Case 1: 전체 region 0 (균일 파란색)
│   │   │                            # Case 2: 4-region (파랑/주황/분홍/청록)
│   │   │                            # _estimate_stress(): 물리 기반 Case 차별화
│   │   └── real_runner.py          # 실제 Abaqus subprocess (ABAQUS_MODE=real)
│   │                                # _run_cae_script(): abaqus cae -noGUI *.py -- args result
│   │                                # _run_python_script(): abaqus python *.py (standalone)
│   │                                # submit_job(): 해석 완료 후 export_vtk.py 자동 실행
│   │
│   ├── ai/
│   │   ├── claude_client.py        # AsyncAnthropic 싱글턴
│   │   ├── pattern_classifier.py   # Vision 기반 형상 패턴 분류
│   │   │                            # lateral_tee / t_joint_90 / y_joint / elbow /
│   │   │                            # straight_pipe / multi_branch / unknown
│   │   ├── cut_rules.py            # 패턴별 결정론적 rule sets (dispatch table)
│   │   │                            # RULE_SETS[pattern](geometry_params) → cut_planes
│   │   ├── cut_advisor.py          # ★ Vision-primary 오케스트레이터
│   │   │                            # 1단계: annotated screenshots → Claude Vision
│   │   │                            # 2단계: 이미지에서 복잡 구간 시각 추정 + 위치 결정
│   │   │                            # rules는 참고값/sanity bound만
│   │   │                            # _postprocess(): BB클램프 + branch cut guard
│   │   │                            # rule_based_fallback(): API 없을 때
│   │   └── result_analyzer.py      # 해석 결과 AI 요약 (claude-sonnet-4-20250514)
│   │
│   ├── api/
│   │   ├── jobs.py                 # Job CRUD, 파일 업로드, DELETE, history
│   │   ├── geometry.py             # STL/VTK 서빙, /surface 엔드포인트
│   │   ├── cut.py                  # 커팅 제안/승인 (_bg_suggest → async def)
│   │   └── results.py              # 해석 결과 조회
│   │
│   └── db/
│       ├── models.py               # Job, CutSuggestion SQLAlchemy 모델
│       └── migrations/             # Alembic
│
├── frontend/src/
│   ├── pages/
│   │   ├── Jobs.tsx                # 작업 목록, 복수선택 삭제, 체크박스
│   │   ├── JobDetail.tsx           # 타임라인 히스토리 (각 단계 접기/펼치기)
│   │   ├── CutReview.tsx           # ★ 커팅 검토 (PatternCard + visual_analysis 표시)
│   │   └── Report.tsx              # 해석 결과 (메시/형상 탭 + 전체화면 토글)
│   ├── components/
│   │   ├── GeometryViewer.tsx      # Three.js STL + oblique cut planes (quaternion 회전)
│   │   │                            # branch plane: 주황색, X/Y/Z plane: 파란색
│   │   ├── CutPlaneControl.tsx     # 축정렬 슬라이더 + BranchPlaneCard (read-only)
│   │   └── MeshViewer.tsx          # ★ VTK 파서 + region 컬러 + cell-edge wireframe
│   │                                # cell connectivity에서 직접 edge 추출 (각도 무관)
│   ├── hooks/useJob.ts             # pollInterval=0 → 단발 fetch (무한루프 방지)
│   └── types/job.ts                # CutPlane: axis "branch" + normal/point/angle_deg
│
├── abaqus_scripts/                 # 실제 Abaqus CAE 스크립트 (Phase 2)
│   ├── mesh_case1.py               # Case 1: 전체 TET/FREE → HEX/SWEEP 시도
│   ├── mesh_case2.py               # Case 2: X-cut(DatumPlaneByPrincipalPlane) +
│   │                                #   branch oblique(DatumPlaneByPointNormal) → 파티션 메시
│   ├── apply_bc.py                 # 재료/BC/하중 → .inp 수정 (*_bc.inp 출력)
│   │                                # NSET-INLET/OUTLET, SURF-INNER 는 플레이스홀더
│   │                                # → 실제 Abaqus PC에서 확인 후 교체 필요
│   └── export_vtk.py               # .odb → VTK ASCII (stress + displacement)
│                                    # abaqus python export_vtk.py 로 실행 (standalone)
│                                    # CELL_DATA: mises(float), POINT_DATA: displacement_mag
│
└── tests/fixtures/tk-no3.X_T      # Case 2 테스트 파일 (Lateral Tee 45°)
```

---

## Phase 1 완료 현황

| 기능 | 상태 | 비고 |
|------|------|------|
| Docker Compose + DB | ✅ | 포트 8001/5174/5433/6380 |
| 파일 업로드 + Job 파이프라인 | ✅ | output_dir/uploads/ 저장 (watch_dir 저장 시 중복 Job 생성 버그) |
| geometry_parser | ✅ | pythonOCC + heuristic fallback (X_T) |
| geometry_exporter (STL) | ✅ | bounding_box 기반 branch 길이, outward-only branch |
| geometry_renderer (Vision용 PNG) | ✅ | junction 마커 + OD 스케일바 |
| Vision-primary 커팅 제안 | ✅ | 이미지로 복잡 구간 시각 추정, rules는 참고만 |
| 형상 패턴 분류기 | ✅ | lateral_tee / t_joint_90 / y_joint / unknown 등 7종 |
| 패턴별 rule sets | ✅ | cut_rules.py dispatch table |
| Oblique branch cut plane | ✅ | axis:"branch" + normal/point 스키마 |
| 커팅 4개 (Header×2 + Branch×2) | ✅ | 하단=OD×0.5, 상단=OD×1.5 |
| Bounding box 클램프 | ✅ | 커팅 평면이 형상 밖으로 나가지 않음 |
| MockAbaqusRunner | ✅ | synthetic surface quad mesh |
| 메시 밀도 (seed_size 기반) | ✅ | 30k 상한, 각도 무관 wireframe |
| Case 1/2 메시 색상 구분 | ✅ | Case 1=전체 파란, Case 2=4-region 다색 |
| 품질 검사 규칙 엔진 | ✅ | Case1/2별 max_aspect_ratio, element_count |
| 해석 결과 (물리 기반) | ✅ | thin-wall + ASME B31.3 SIF, Case 차별화 |
| AI 리포트 생성 | ✅ | claude-sonnet-4-20250514 |
| Job 삭제 (복수선택) | ✅ | 체크박스 + 모달, 파일도 정리 |
| Job 히스토리 타임라인 | ✅ | GET /api/jobs/{id}/history |
| Report 전체화면 | ✅ | 뷰어 + 요약 + AI 리포트 오버레이 |

---

## 목표 파이프라인 아키텍처 (Phase 3 방향)

지금까지 논의로 확정된 전체 방향. Phase별로 단계적 구현.

```
CAD (STEP / X_T)
    ↓
Feature extraction                          ← Phase 3
  - OpenCASCADE → BREP Graph 생성
  - cylinder / torus / sphere / plane 인식
  - 인터페이스 / 교선 / 접합 타입 추출
    ↓
Rule-based initial partition
  - 알려진 패턴 → 규칙으로 먼저 파티션 시도
  - 규칙 성공 → AI 호출 없음 (빠르고 일관성)
    ↓
Sweepability analysis  ← 1차 검증            ← Phase 3
  - 각 cell Sweepable 여부 Abaqus로 확인
  - 성공 → Hex meshing
  - 실패 → AI partition refinement
    ↓
AI partition refinement  (실패 케이스만)
  - BREP Graph(JSON) + 형상 이미지(Vision) 입력
  - Sweepability 실패 원인 피드백 포함
  - 재조정 제안
    ↓
Sweepability analysis  ← 2차 검증
  - 통과 → Hex meshing
  - 반복 실패 → Tet fallback + 사람 알림
    ↓
Hex meshing (Sweep + Structured)
  파라미터 결정 (규칙 기반, AI 불필요):
  - 두께 방향 레이어 수 = max(4, round(thickness / seed_size))
  - 원주 방향 분할 수 = round(2π × radius / seed_size)
  - 요소 크기 = thickness / layer_count (종횡비 1:10 역산)
  - 영역 간 요소 크기 매칭 → 규칙 충돌 시만 AI 보조
    ↓
Tet fallback
  - Hex 불가 영역에만 적용 (FREE meshing, 완전 자동)
    ↓
Quality optimization loop
  - 종횡비(≤1:10) / 야코비안(>0) / 요소수 / 두께 레이어(≥4)
  - 실패 → seed size 자동 조정 후 재메시 (최대 5회)
  - 반복 실패 → AI 원인 진단
    ↓
BC / 물성 / 하중 적용
    ↓
해석 실행 (Abaqus Job submit)
    ↓
결과 파싱 + AI 리포트
    ↓
(Phase 3) Convergence Study 자동화
  - seed_size 3단계 반복 (coarse / medium / fine)
  - AI 수렴 여부 판단
  - "형상 타입 + seed_size → 수렴 보장" DB 축적
```

---

## AI 역할 분담 (명확한 경계)

```
AI 담당
  1. 중요 영역 인식
     - BREP Graph + Vision으로 응력 집중부 판별
     - 형상 패턴 분류 (lateral_tee / elbow / vessel 등)

  2. 파티션 추천 + Sweepability 실패 시 재조정
     - unknown 패턴 → confidence low → 사람 검토 강제

  3. 영역 간 요소 크기 매칭 (규칙 충돌 시만)

  4. 해석 결과 해석 + 리포트
     - 숫자 → 엔지니어링 판단 (안전율, 위험 부위, 개선 방향)

규칙(코드) 담당 — AI 절대 불필요
  - 두께 방향 레이어 수 계산
  - 요소 크기 역산 (두께 기반)
  - 원주 방향 분할 수
  - 종횡비 / 야코비안 / 요소수 검사
  - Sweepability 검증 (pass/fail)
  - seed size 재조정 (최대 5회 자동)
  - Case 1/2 분류 (Manual 유지)
```

---

## Abaqus 이중 환경 (핵심 제약)

Abaqus는 자체 Python 인터프리터를 내장. FastAPI와 직접 통신 불가.
**반드시 JSON 파일로만 데이터 교환.**

```
FastAPI (일반 Python 3.11)          Abaqus 내장 Python (별도 환경)
────────────────────────────        ────────────────────────────────
Claude API 호출                     from abaqus import *  ← 여기서만 작동
DB 저장                             from abaqusConstants import *
params.json 생성                    params.json 읽기
subprocess로 Abaqus 실행    →       메시 / 파티션 / 해석 실행
result.json 읽기            ←       result.json 저장
Three.js 렌더링                     VTK export
```

```python
# 운영: 헤드리스 (화면 없음)
subprocess.run(["abaqus", "cae", "-noGUI", "script.py"])

# 디버깅: GUI 열림 → 파티션/메시 눈으로 확인
# ABAQUS_DEBUG=true 환경변수로 전환
subprocess.run(["abaqus", "cae", "script.py"])
```

**Abaqus 내장 Python 제약:**
- pip 패키지 설치 불가 (numpy 등 일부만 기본 포함)
- Python 버전은 Abaqus 버전마다 다름 (설치 후 확인 필요)
- FastAPI / 외부 라이브러리 import 불가

---

## Abaqus 완전 이전 계획

```
현재: MockRunner(synthetic) + RealRunner(Abaqus) 병행
목표: RealRunner 단일화 (Mock 제거)

현재 레포에서 단계적 진행 (신규 레포 불필요)
  Phase 2 완료 → ABAQUS_MODE=real 안정화
               → MockRunner deprecated 표시
  Phase 3 시작 → MockRunner 완전 제거
               → AbaqusInterface 추상 레이어 단순화
               → AbaqusRunner 단일 클래스로 통합
```

---

## AI 입력 전략 (Phase 3 방향: BREP Graph + Vision)

현재는 수치 파라미터 + Vision 이미지 조합.
Phase 3에서 BREP Graph를 추가해 위상 관계까지 AI가 이해하도록 확장.

```python
# Phase 3 AI 입력 구조
{
  # 1. BREP Graph (텍스트) → 위상 관계 이해
  "brep_graph": {
    "bodies": [
      {"id": "B1", "type": "cylinder",
       "radius": 432, "length": 2800, "axis": [1,0,0]},
      {"id": "B2", "type": "cylinder",
       "radius": 216, "length": 900,
       "axis": [0, 0.707, 0.707]}
    ],
    "interfaces": [
      {"type": "intersection", "bodies": ["B1","B2"],
       "curve_type": "ellipse",
       "center": [1400, 0, 0], "fillet_R": 50}
    ]
  },

  # 2. 형상 이미지 3각도 (Vision) → 직관적 형상 파악
  # annotated PNG: junction 마커 + OD 스케일바

  # 3. 수치 파라미터 (정확한 치수 계산용)
  "geometry_params": { ... }
}
```

---

## 파티션 템플릿 DB (Phase 3)

케이스 축적 후 동일 패턴은 AI 없이 템플릿 직접 적용.

```python
PARTITION_TEMPLATES = {
    "lateral_tee_45deg": {
        "header_cut_ratio": 1.5,       # header_OD × 1.5
        "branch_lower_ratio": 0.5,     # branch_OD × 0.5
        "branch_upper_ratio": 1.5,     # branch_OD × 1.5
        "sweep_regions": ["header_left", "header_right", "branch_straight"],
        "tet_regions": ["junction_zone"],
        "layer_rules": {"thickness": 4, "circumference": 12},
        "verified_cases": 0,           # 실무자 승인 누적 수
    },
}

def match_template(feature_graph):
    match = find_closest_template(feature_graph)
    if match.confidence > 0.9:
        return match.template    # AI 호출 없음
    return None                  # AI로 넘어감
```

---

## 커팅 제안 구조 (Vision-primary, 현재 구현)

### 흐름

```
geometry_renderer → annotated PNG (junction × 마커 + OD scale bar)
    ↓
Claude Vision: 이미지에서 복잡 구간 시각 추정
  - header_complexity_extent_mm
  - branch_complexity_extent_mm
  - rule_vs_visual: 규칙과 이미지 비교 분석
    ↓
위치 결정: 이미지 관찰 우선, rules는 참고값
    ↓
_postprocess(): bounding box 클램프 + branch cut guard
```

### 커팅 평면 스키마

```python
# 축 정렬
{"axis": "X"|"Y"|"Z", "offset": float, "reason": str}

# Branch 수직 oblique plane
{
    "axis": "branch",
    "offset": float,           # junction에서 branch 축 방향 거리 (mm)
    "normal": [nx, ny, nz],    # branch 축 단위벡터 = 평면 법선
    "point": [x, y, z],
    "angle_deg": float,
    "reason": str,
}
```

### 총 4개 커팅 (Lateral Tee 기준)

```
Branch 상단 ② ──── OD×1.5  (Auto Mesh 끝)
      │
      │  ← Auto Mesh (Tet)
      │
Branch 하단 ① ──── OD×0.5  (Auto Mesh 시작)
      │
─[X좌측]──[header][junction][header]──[X우측]─
  Map Hex              Auto Tet           Map Hex
```

### 커팅 수정 이력 → 룰 고도화

```
CutSuggestion 테이블에 저장:
  ai_suggestion / final_cut / adjustment_mm
  engineer_comment  ← ★ 승인 UI에서 반드시 입력받을 것
                       (이유 없으면 패턴 분석 불가)

10~20건:  Few-shot 예시 프롬프트 주입
50건+:    수정 패턴 분석 → 룰 계수 정제
200건+:   유사 형상 자동 승인 (adjustment < 10mm)
```

---

## 해석 결과 계산 (Mock — 물리 기반)

```
σ_hoop = P × r_mean / t              (thin-wall hoop stress)
SIF    = 0.9 / β^0.5 × angle_factor × fillet_factor  (ASME B31.3 간이식)

Case 1 (균일 메시):
  sif = sif_base × 0.80   → mesh smearing으로 응력 20% 과소평가

Case 2 (파티션 메시):
  junction_capture_factor = 1.10 ~ 1.40  (커팅 위치 함수)
  sif = sif_base × junction_capture_factor
  → Vision cuts > Rule cuts 항상 성립 (junction 근처 정밀 격리)
```

---

## 메시 품질 규칙

```python
QUALITY_RULES = {
    "case1": {
        "max_aspect_ratio": 10.0,            # 종횡비 최대 1:10
        "min_elements_through_thickness": 4,  # 두께 방향 최소 4요소
        "max_element_count": 300_000,
        "min_jacobian": 0.0,                  # 전 요소 양수
    },
    "case2": {
        "max_aspect_ratio": 10.0,
        "min_elements_through_thickness": 4,
        "max_element_count": None,            # 핑크 영역 품질 우선, 요소수 제한 없음
        "min_jacobian": 0.0,
    },
}
```

---

## 메시 시각화 (MeshViewer)

### VTK 파일 종류

```
Mock VTK (mock_runner.py):
  CELL_TYPES M → 9 (Quad)
  SCALARS region int 1 → 0~3 (region 팔레트)

Real Abaqus VTK (export_vtk.py):
  CELL_TYPES M → 10(Tet4) / 12(Hex8) / 13(Wedge6) / 24(Tet10) / 25(Hex20)
  SCALARS mises float 1 → Von Mises per element (MPa)
  SCALARS displacement_mag float 1 → per node (사용 안 함, 현재)
```

### 핵심 설계

```typescript
// EdgesGeometry(angle) 사용 금지 — 파이프 표면 엣지 안 그려짐
// → 외부 face에서 직접 edge 추출 (각도 무관)

// volumetric: face counting으로 내부면 제거
const faceMap = new Map<string, {verts, count, region, mises}>();
for each cell: cellFaces(type, verts) → faceMap 집계
// count==1인 face만 렌더 (isVolume=true)
// wireframe: wireRef.current.visible 직접 토글 (re-parse 없음)
```

### 메시 밀도

```python
n_circ  = int(2π × radius / seed_size)
n_axial = int(length / seed_size)
# 30,000 quads 상한으로 비율 유지하며 스케일
if estimated > 30_000:
    scale = sqrt(30_000 / estimated)
```

---

## Abaqus 추상화 레이어 (절대 규칙)

**`AbaqusInterface`를 거치지 않고 직접 subprocess 호출 금지.**

```python
class AbaqusInterface(ABC):
    def run_mesh_case1(self, step_file, params, geometry_params=None) -> dict: ...
    def run_mesh_case2(self, step_file, params, cut_planes, geometry_params=None) -> dict: ...
    def apply_bc(self, inp_file, bc_params) -> dict: ...
    def submit_job(self, inp_file, geometry_params=None, bc_params=None,
                   case_type="case1", mesh_result=None, cut_planes=None) -> dict: ...
```

---

## API 엔드포인트

```
POST   /api/jobs/upload
GET    /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs/{id}/case-type
DELETE /api/jobs/{id}
GET    /api/jobs/{id}/history

GET    /api/jobs/{id}/cut-suggestion
POST   /api/jobs/{id}/cut-approve    # cut_planes + engineer_comment 포함
GET    /api/jobs/{id}/surface        # Binary STL
GET    /api/jobs/{id}/vtk
GET    /api/jobs/{id}/mesh-preview

POST   /api/jobs/{id}/start-solve
GET    /api/jobs/{id}/results
```

---

## Docker 포트

```
backend  : 8001 (내부 8000)
frontend : 5174 (내부 5173)
postgres : 5433 (내부 5432)
redis    : 6380 (내부 6379)
```

컨테이너 간 연결은 서비스명으로:
- `DATABASE_URL=postgresql://feauser:feapass@db:5432/fea_automation`
- `REDIS_URL=redis://redis:6379`

```bash
# .env 변경 후 반드시 force-recreate
docker compose up -d --force-recreate backend worker
```

---

## 환경변수 (.env)

```bash
ABAQUS_MODE=mock            # mock | real
ABAQUS_PATH=...             # real 모드만
WORK_DIR=...                # real 모드만
ABAQUS_DEBUG=false          # true → GUI 있는 모드 (디버깅용)
DATABASE_URL=postgresql://feauser:feapass@localhost:5432/fea_automation
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...
WATCH_DIR=./watch_dir
OUTPUT_DIR=./output_dir
```

---

## 테스트 파일

```
tests/fixtures/tk-no3.X_T
  형상: Lateral Tee (비스듬한 분기관)    Case: 2
  Header OD: 864mm  ID: 764mm  두께: 50mm  길이: 2800mm
  Branch OD: 432mm  ID: 382mm
  접합 각도: 45°  Junction: X=1400mm  Fillet: 50mm
  BBox: X[-100,2900] Y[-500,500] Z[-500,1200]

Vision 제안 결과 (2026-05-18):
  Pattern: lateral_tee  Confidence: medium
  X=700mm / X=2100mm  Branch 하단 300mm / 상단 648mm
  mises=114MPa  SF=1.21

목표 메시 품질 레퍼런스:
  IMG_5419.PNG — Case 2 혼합 메시 (핑크/그린/노란)
  IMG_5426.PNG — 노즐-쉘 접합부 100% Hex (최고 품질 목표)
  IMG_5421.PNG — Case 1 100% Structured Hex
```

---

## Phase 2 현황 — 실제 Abaqus PC 연동

Phase 2 목표: ABAQUS_MODE=real 전환만으로 동작 (코드 변경 없이)

### ✅ 완료

| 항목 | 비고 |
|------|------|
| RealAbaqusRunner | `_run_cae_script` + `_run_python_script` |
| mesh_case2.py oblique cut | `DatumPlaneByPointNormal` 구현 |
| export_vtk.py (.odb → VTK) | mises + displacement_mag |
| apply_bc.py | 구현됨 — node set은 플레이스홀더 |
| MeshViewer volumetric VTK | face counting 외면 추출, mises jet colormap (2026-05-19) |

#### MeshViewer volumetric 파싱 상세

```
동작:
  - CELL_TYPES 파싱 → isVolume 판별
  - face table로 각 cell의 face 생성 후 Map 집계
    Tet4/Tet10(24): TET4_FACES 4개 삼각형
    Hex8/Hex20(25): HEX8_FACES 6개 사각형
    Wedge6(13)    : WEDGE6_FACES 2삼각+3사각
  - isVolume=true: count==1 face만 렌더 (내부 공유면 제거)
  - isVolume=false: 기존 동작 유지 (mock surface quad)
  - SCALARS mises  → jet colormap (blue→cyan→green→yellow→red)
  - SCALARS region → region 팔레트 (mock 전용)
  - wireframe: wireRef 직접 토글 (re-parse 없음)

범례:
  - mock: region 색상 범례
  - real: Von Mises 컬러바 (min/max MPa) + "volumetric" 표시
```

| BC/하중 입력 UI | ✅ | mesh_done 상태에서 BcSettingsPanel 표시 (2026-05-19) |

#### BC/하중 UI 상세

```
위치: JobDetail → ActionBar → mesh_done 상태
구성: BcSettingsPanel (재료 선택 + 내압 + 허용응력 + E/ν + 고정단)
동작: POST /api/jobs/{id}/bc-params 저장 → POST /api/jobs/{id}/start-solve

재료 프리셋 (선택 시 E/ν/허용응력 자동 입력, CUSTOM은 직접 편집):
  STEEL_A106_GrB   : E=200000 MPa, ν=0.3, σ_allow=138 MPa
  STEEL_A312_TP316 : E=195000 MPa, ν=0.3, σ_allow=115 MPa
  CUSTOM           : 직접 입력

기존 bc_params pre-fill:
  API _to_out() 이제 bc_params 포함
  Job 타입에 BcParams 인터페이스 추가
  useEffect로 existingBcParams → 폼 상태 동기화

버튼 라벨: 최초="저장 후 해석 시작" / 재실행="재해석 시작"
```

### ❌ 미완 (다음 작업 대상)

```
1. apply_bc.py node set 플레이스홀더 교체
   NSET-INLET / NSET-OUTLET / SURF-INNER
   → 실제 Abaqus PC에서 메시 열람 후 정의

2. 실제 Abaqus PC 통합 테스트
   ABAQUS_MODE=real 전환
   tk-no3.X_T → mesh_case2.py → apply_bc.py → submit → export_vtk.py
```

---

## Phase 3 (고도화)

```
아키텍처
  - topology_graph.py + feature_extractor.py 구현
  - BREP Graph 기반 AI 입력으로 전환
  - Sweepability analysis 루프 구현
  - 파티션 템플릿 DB 구축
  - MockRunner 제거 → Abaqus 완전 이전

메시 품질
  - Convergence Study 자동화
  - 템플릿별 최적 seed_size DB 축적

AI 고도화
  - engineer_comment 이력 → 룰 자동 개선
  - 유사 형상 자동 승인 (adjustment < 10mm + confidence high)
  - unknown 패턴 처리 강화

기타
  - SolidWorks 자동 export 트리거
  - Fortran User Subroutine 연동 (UMAT 등)
```

---

## 절대 하지 말 것

- `AbaqusInterface`를 거치지 않고 subprocess 직접 호출
- AI를 품질 검사 / seed size 단순 계산에 사용 (규칙으로 처리)
- Case 1/2 분류를 AI로 자동화 (Manual 유지)
- 커팅 위치를 AI 제안만으로 자동 확정 (반드시 사람 승인)
- 환경변수 없이 하드코딩된 경로 사용
- FastAPI async background task에서 `asyncio.run()` 사용
  → anyio 이벤트 루프 충돌 → task 조용히 실패 → DB 저장 안 됨
  → 반드시 `async def` background task로 작성
- `.env` 변경 후 `docker compose restart` → `force-recreate` 필수
- `EdgesGeometry(angle)` 사용 → 파이프 표면 엣지 안 그려짐
  → cell connectivity에서 직접 edge 추출
- API 업로드 파일을 `watch_dir`에 저장 → 중복 Job 생성
  → 반드시 `output_dir/uploads/`에 저장
- Abaqus 내장 Python에서 FastAPI / 외부 pip 패키지 import 시도
  → FastAPI ↔ Abaqus는 반드시 JSON 파일로만 통신
