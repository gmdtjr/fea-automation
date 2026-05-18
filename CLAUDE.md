# FEA Automation System — CLAUDE.md

Claude Code 핸드오프 문서. 이 파일을 먼저 읽고 모든 구현을 시작할 것.

---

## 프로젝트 개요

SolidWorks(STEP / Parasolid X_T) → Abaqus 메시 생성 → 해석까지 파이프라인을 자동화하는 시스템.

핵심 설계 원칙:
- Abaqus 없는 PC에서도 개발/테스트 가능 (MockRunner + synthetic mesh)
- 커팅 위치는 Vision-primary AI가 제안 → 사람이 3D 뷰어에서 검토/수정/승인 (Human-in-the-loop)
- AI는 꼭 필요한 곳에만 (커팅 제안, 결과 해석)
- 나머지는 규칙 기반으로 처리

---

## 기술 스택

```
Backend    : FastAPI + Python 3.11
DB         : PostgreSQL + SQLAlchemy 2.0
Queue      : Redis + Celery (비동기 태스크)
Frontend   : React + TypeScript + Vite + Tailwind CSS
3D 뷰어    : Three.js (STL 렌더링 + oblique cut planes + 메시 surface viz)
AI         : claude-sonnet-4-6 (Anthropic SDK)
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
│   │   └── report_generator.py     # 해석 결과 리포트 생성
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
│   │   │                            # _estimate_stress(): 물리 기반 Case 차별화 (아래 상세)
│   │   └── real_runner.py          # 실제 Abaqus subprocess (Phase 2)
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
│   │   └── result_analyzer.py      # 해석 결과 AI 요약 (claude-sonnet-4-6)
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
│   ├── mesh_case1.py
│   ├── mesh_case2.py               # oblique cut plane 지원 필요 (DatumPlaneByPointNormal)
│   └── apply_bc.py
│
└── tests/fixtures/tk-no3.X_T      # Case 2 테스트 파일 (Lateral Tee 45°)
```

---

## Phase 1 완료 현황

### ✅ 완료된 항목

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
| Case 1/2 응력 차별화 | ✅ | Case1=smearing 80%, Case2=capture 110~140% (커팅 위치 함수) |
| AI 리포트 생성 | ✅ | claude-sonnet-4-6 |
| Job 삭제 (복수선택) | ✅ | 체크박스 + 모달, 파일도 정리 |
| Job 히스토리 타임라인 | ✅ | GET /api/jobs/{id}/history, 각 단계 접기/펼치기 |
| Report 전체화면 | ✅ | 뷰어 + 요약 + AI 리포트 오버레이 |
| STL/VTK 형상 일치 | ✅ | 동일 bounding_box 기반 branch 길이 |

---

## 커팅 제안 구조 (Vision-primary)

### 흐름

```
1. geometry_renderer → annotated PNG (junction × 마커 + OD scale bar)
2. Claude Vision: 이미지에서 복잡 구간 시각 추정
   - header_complexity_extent_mm: junction에서 복잡 구간이 끝나는 지점
   - branch_complexity_extent_mm: branch 방향 복잡 구간
   - rule_vs_visual: 규칙과 이미지 비교 분석
3. 위치 결정: 이미지 관찰 우선, rules는 참고값
4. _postprocess(): bounding box 클램프 + branch cut guard
```

### 커팅 평면 스키마

```python
# 축 정렬
{"axis": "X"|"Y"|"Z", "offset": float, "reason": str}

# Branch 수직 oblique plane
{
    "axis": "branch",
    "offset": float,          # junction에서 branch 축 방향 거리 (mm)
    "normal": [nx, ny, nz],  # branch 축 단위벡터 = 평면 법선
    "point": [x, y, z],      # junction + normal × offset
    "angle_deg": float,
    "reason": str,
}
```

### 총 4개 커팅 (Lateral Tee 기준)

```
Branch 상단 ② ──── OD×1.5  (Auto Mesh 끝)
      │
      │  ← Auto Mesh (Tet) ← 주황색
      │
Branch 하단 ① ──── OD×0.5  (Auto Mesh 시작)
      │
─[X 좌측]──[header][junction][header]──[X 우측]─
  파란색(Map)    주황색(Auto)           파란색(Map)
```

### AI 전략: Vision 분류 + 규칙 계산

```
Vision → 형상 패턴 분류 (pattern_classifier.py)
       + 복잡 구간 시각 추정 + 커팅 위치 직접 결정 (cut_advisor.py)
             ↓                    ↓
         알려진 패턴          unknown / confidence:low
     cut_rules.py 참고         → 커팅 비워둠
     + Vision 이미지 조정       → 사람 수동 입력 강제
             ↓
     _postprocess() → BB클램프 + branch cut 누락 보완
```

### 주요 로직

- `_branch_len_from_bbox()`: Y/Z 각각 추정 후 max → 단위 자동 감지 (≤10 → m)
- `_extract_json()`: multi-line string 포함 JSON 파싱 (robust)
- `_build_prompt()`: rules를 참고값으로만 표시, 이미지 기반 판단 유도

---

## 해석 결과 계산 (Mock — 물리 기반)

실제 Abaqus 없이 thin-wall 배관 공학식으로 추정.

```
σ_hoop = P × r_mean / t              (thin-wall hoop stress)
SIF    = 0.9 / β^0.5 × angle_factor × fillet_factor  (ASME B31.3 간이식)

Case 1 (균일 메시):
  sif = sif_base × 0.80
  → junction에서 mesh smearing으로 응력 20% 과소평가 (낮은 값, 비보수적)

Case 2 (파티션 메시):
  junction_capture_factor = 1.10 ~ 1.40  (커팅 위치 함수)
  - 커팅이 junction에 가까울수록 높음 (정밀 격리 → 실제 응력 집중 정확 포착)
  - header_cut_dist / header_OD 비율로 계산
  sif = sif_base × junction_capture_factor

→ Case 2 > Case 1 항상 성립 (파티션이 더 정확한 응력 포착)
→ Vision cuts (junction 근처) > Rule cuts (junction에서 멀리) 성립
```

---

## 메시 시각화 (MeshViewer)

### VTK 파일 구조

```
POINTS N float
CELLS M (quad=9, tri=5)
CELL_DATA M
SCALARS region int 1
  0 = Header Map/Hex (파란색)   ← Case 1: 전체 0
  1 = Junction Auto/Tet (주황)  ← Case 2만
  2 = Branch Auto/Tet (분홍)    ← Case 2만
  3 = Branch Map/Hex (청록)     ← Case 2만
```

### 핵심 설계

```typescript
// EdgesGeometry(20°) 사용 금지!
// 파이프 표면 인접 quad 각도 ≈ 1.7° → 엣지 대부분 안 그려짐
// → cell connectivity에서 직접 edge 추출 (각도 무관)
const edgeSet = new Set<string>();  // 중복 제거
for each cell: 각 edge (v_a, v_b) → edgeSet에 추가 → LineSegments
```

### 메시 밀도

```python
# seed_size 기반 자동 계산
n_circ = int(2π × radius / seed_size)
n_axial = int(length / seed_size)
# 30,000 quads 상한으로 비율 유지하며 스케일
if estimated > 30_000:
    scale = sqrt(30_000 / estimated)
    n_circ = int(n_circ * scale)
    n_axial = int(n_axial * scale)
```

---

## Abaqus 추상화 레이어 (절대 규칙)

**`AbaqusInterface`를 거치지 않고 Gmsh나 subprocess를 직접 호출하지 말 것.**

```python
class AbaqusInterface(ABC):
    def run_mesh_case1(self, step_file, params, geometry_params=None) -> dict: ...
    def run_mesh_case2(self, step_file, params, cut_planes, geometry_params=None) -> dict: ...
    # cut_planes: [{"axis":"X","offset":mm} | {"axis":"branch","normal":...,"point":...}]
    def apply_bc(self, inp_file, bc_params) -> dict: ...
    def submit_job(self, inp_file, geometry_params=None, bc_params=None,
                   case_type="case1", mesh_result=None, cut_planes=None) -> dict: ...
```

---

## API 엔드포인트

```
POST   /api/jobs/upload              # STEP/X_T 업로드 → Job 생성 (output_dir/uploads/ 저장)
GET    /api/jobs                     # 작업 목록
GET    /api/jobs/{id}                # 작업 상세
POST   /api/jobs/{id}/case-type      # Case 1/2 선택
DELETE /api/jobs/{id}                # Job + 관련 파일 삭제
GET    /api/jobs/{id}/history        # 전체 단계 이력 (타임라인용)

GET    /api/jobs/{id}/cut-suggestion # 커팅 제안 (없으면 background 생성)
POST   /api/jobs/{id}/cut-approve    # 커팅 승인 (cut_planes 배열)
GET    /api/jobs/{id}/surface        # Binary STL (3D 뷰어용, lazy 생성)
GET    /api/jobs/{id}/vtk            # VTK 파일 (메시 결과)
GET    /api/jobs/{id}/mesh-preview   # 메시 통계 + vtk_url

POST   /api/jobs/{id}/start-solve    # 해석 시작
GET    /api/jobs/{id}/results        # 해석 결과 + AI 리포트
```

---

## Docker 포트 (다른 프로젝트와 충돌 방지)

```
backend  : 8001 (내부 8000)
frontend : 5174 (내부 5173)
postgres : 5433 (내부 5432)
redis    : 6380 (내부 6379)
```

컨테이너 간 연결은 docker-compose `environment:` 섹션에서 서비스명으로 override:
- `DATABASE_URL=postgresql://feauser:feapass@db:5432/fea_automation`
- `REDIS_URL=redis://redis:6379`

**`.env` 변경 후 `docker compose restart`는 env 반영 안 됨 → `force-recreate` 필수:**
```bash
docker compose up -d --force-recreate backend worker
```

---

## 환경변수 (.env)

```bash
ABAQUS_MODE=mock          # mock | real
ABAQUS_PATH=...           # real 모드만
WORK_DIR=...              # real 모드만
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
  형상: Lateral Tee (비스듬한 분기관)
  Case: 2 (복잡, 커팅 필요)
  Header OD: 864mm  ID: 764mm  두께: 50mm  길이: 2800mm
  Branch OD: 432mm  ID: 382mm
  접합 각도: 45°  Junction: X=1400mm
  Fillet: 50mm
  BBox: X[-100,2900] Y[-500,500] Z[-500,1200]

Vision 제안 결과 (2026-05-18):
  Pattern: lateral_tee  Confidence: medium
  X=700mm / X=2100mm  (규칙 104/2696보다 훨씬 좁음 — 복잡 구간 500~600mm 관찰)
  Branch 하단 300mm / 상단 648mm
  → mises=114MPa  SF=1.21  (Vision cuts, 정밀 격리)
```

---

## 다음 작업: Phase 2 — 실제 Abaqus PC

```
Phase 2 목표: ABAQUS_MODE=real 전환만으로 동작 (코드 변경 없이)

1. RealAbaqusRunner 완성
   - abaqus_scripts/mesh_case2.py: oblique cut plane 지원 추가
     현재: DatumPlaneByPrincipalPlane (axis-aligned만)
     필요: DatumPlaneByPointNormal(point, normal) 으로 branch oblique plane 처리
   - abaqus_scripts/apply_bc.py: 실제 재료/BC/하중 적용
   - abaqus_scripts/export_vtk.py: .odb → VTK 변환 (응력 컬러맵 포함) → 신규 작성

2. .odb / .dat 파싱
   - Abaqus Python: odb.steps['Step-1'].frames[-1].fieldOutputs
   - max Von Mises, 변위, 응력 위치 추출
   - analysis_result 동일 스키마로 저장 (UI 변경 불필요)

3. BC/하중 설정 UI (현재 bc_params 항상 null)
   - 내압(pressure_mpa), 재료(material), 경계조건 종류 입력 폼
   - Job 생성 시 또는 mesh 완료 후 별도 단계

4. 실제 VTK로 MeshViewer 동작 확인
   - Abaqus VTK는 volumetric elements (Tet4, Hex8)
   - MeshViewer의 VTK 파서가 hex 요소 지원하는지 확인
   - 필요 시 VTK_HEXAHEDRON(type 12) 파싱 추가

5. 실제 형상 STL
   - geometry_exporter.py: Gmsh로 X_T 직접 로드 → surface STL (x86_64)
   - ARM64에서도 품질 좋은 합성 STL이 이미 동작 중

Phase 2 이후 (Phase 3 — 선택):
  - Vision 형상 패턴 분류기 고도화 (unknown 패턴 처리)
  - 커팅 수정 이력 → 룰 자동 개선
  - 유사 형상 자동 승인 (confidence high + 수정량 0)
  - SolidWorks 자동 export 트리거
```

---

## 절대 하지 말 것

- `AbaqusInterface`를 거치지 않고 Gmsh나 subprocess를 직접 호출
- AI를 품질 검사나 seed size 계산에 사용 (규칙으로 처리)
- Case 1/2 분류를 AI로 자동화 (Manual 유지)
- 커팅 위치를 AI 제안만으로 자동 확정 (반드시 사람 승인 필요)
- 환경변수 없이 하드코딩된 경로 사용
- FastAPI async 엔드포인트의 background task에서 `asyncio.run()` 사용
  → anyio 이벤트 루프 충돌 → task 조용히 실패 → DB 저장 안 됨
  → 반드시 `async def` background task로 작성
- `.env` 변경 후 `docker compose restart` 사용 → `force-recreate` 필수
- `EdgesGeometry(angle)` 사용 → 파이프 표면 엣지 안 그려짐
  → cell connectivity에서 직접 edge 추출
- API 업로드 파일을 `watch_dir`에 저장 → file_watcher가 중복 Job 생성
  → 반드시 `output_dir/uploads/`에 저장
