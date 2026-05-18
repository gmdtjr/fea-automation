import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import type { Job } from "../types/job";
import { useJob } from "../hooks/useJob";

// ── Types ─────────────────────────────────────────────────────────────────────

interface HistoryStep {
  step: string;
  label: string;
  timestamp: string | null;
  data: Record<string, unknown>;
}

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-yellow-600",
  geometry_parsed: "bg-blue-600",
  awaiting_cut_review: "bg-purple-600",
  meshing: "bg-cyan-600",
  mesh_done: "bg-teal-600",
  solving: "bg-orange-600",
  completed: "bg-green-600",
  failed: "bg-red-600",
};

const STEPS_ORDER = [
  "pending", "geometry_parsed", "awaiting_cut_review",
  "meshing", "mesh_done", "solving", "completed",
];

// ── Main page ─────────────────────────────────────────────────────────────────

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { job, loading } = useJob(id!);
  const [history, setHistory] = useState<HistoryStep[]>([]);
  const [openSteps, setOpenSteps] = useState<Set<number>>(new Set([0]));

  useEffect(() => {
    if (!id) return;
    axios.get(`/api/jobs/${id}/history`).then(({ data }) => {
      setHistory(data.steps);
      // Open all steps by default
      setOpenSteps(new Set(data.steps.map((_: unknown, i: number) => i)));
    });
  }, [id, job?.status]); // refetch when status changes

  function toggle(idx: number) {
    setOpenSteps((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  }

  async function setCaseType(caseType: string) {
    await axios.post(`/api/jobs/${id}/case-type`, { case_type: caseType });
    if (caseType === "case2") navigate(`/jobs/${id}/cut-review`);
  }

  async function startSolve() {
    await axios.post(`/api/jobs/${id}/start-solve`);
  }

  if (loading || !job) return <div className="p-8 text-gray-400">Loading...</div>;

  const currentIdx = STEPS_ORDER.indexOf(job.status);

  return (
    <div className="min-h-screen p-8 max-w-4xl mx-auto">
      {/* Back + header */}
      <button onClick={() => navigate("/jobs")} className="text-gray-400 hover:text-white mb-6 text-sm">
        ← 목록으로
      </button>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">{job.file_name}</h2>
          <p className="text-gray-500 text-xs mt-1 font-mono">{job.id}</p>
        </div>
        <span className={`mt-1 px-3 py-1 rounded-full text-xs font-medium ${STATUS_COLOR[job.status] ?? "bg-gray-600"}`}>
          {job.status}
        </span>
      </div>

      {/* Progress bar */}
      <div className="flex gap-1.5 mb-8">
        {STEPS_ORDER.filter(s => job.case_type !== "case1" || s !== "awaiting_cut_review").map((s) => {
          const si = STEPS_ORDER.indexOf(s);
          const done = si < currentIdx;
          const active = si === currentIdx;
          return (
            <div key={s} className="flex-1">
              <div className={`h-1 rounded ${done ? "bg-green-500" : active ? "bg-blue-500" : "bg-gray-700"}`} />
            </div>
          );
        })}
      </div>

      {/* Action buttons */}
      <ActionBar job={job} onSetCase={setCaseType} onStartSolve={startSolve} jobId={id!} navigate={navigate} />

      {/* Error */}
      {job.status === "failed" && job.error_message && (
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 mb-6">
          <p className="text-red-400 font-semibold text-sm">오류 발생</p>
          <p className="text-xs text-gray-300 mt-1 font-mono">{job.error_message}</p>
        </div>
      )}

      {/* Timeline */}
      {history.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-4">진행 이력</h3>
          {history.map((step, idx) => (
            <StepCard
              key={idx}
              step={step}
              idx={idx}
              open={openSteps.has(idx)}
              onToggle={() => toggle(idx)}
              jobId={id!}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Action bar ────────────────────────────────────────────────────────────────

function ActionBar({ job, onSetCase, onStartSolve, jobId, navigate }: {
  job: { status: string; case_type: string | null; bc_params?: Record<string, unknown> | null };
  onSetCase: (t: string) => void;
  onStartSolve: () => void;
  jobId: string;
  navigate: (path: string) => void;
}) {
  if (job.status === "geometry_parsed" && !job.case_type) {
    return (
      <div className="bg-gray-900 rounded-xl p-5 mb-6">
        <p className="text-sm font-medium text-gray-300 mb-3">Case 유형을 선택하세요</p>
        <div className="flex gap-3">
          <button onClick={() => onSetCase("case1")}
            className="flex-1 bg-teal-700 hover:bg-teal-600 rounded-lg p-3 text-left transition">
            <p className="font-bold text-sm">Case 1</p>
            <p className="text-xs text-gray-300 mt-0.5">단순 형상 — 커팅 없음</p>
          </button>
          <button onClick={() => onSetCase("case2")}
            className="flex-1 bg-purple-700 hover:bg-purple-600 rounded-lg p-3 text-left transition">
            <p className="font-bold text-sm">Case 2</p>
            <p className="text-xs text-gray-300 mt-0.5">복잡 형상 — Geo 커팅 필요</p>
          </button>
        </div>
      </div>
    );
  }
  if (job.status === "awaiting_cut_review") {
    return (
      <div className="bg-purple-900/30 border border-purple-700 rounded-xl p-4 mb-6 flex items-center justify-between">
        <div>
          <p className="font-semibold text-sm">커팅 위치 검토 필요</p>
          <p className="text-xs text-gray-400 mt-0.5">AI 커팅 제안을 검토하고 승인하세요.</p>
        </div>
        <button onClick={() => navigate(`/jobs/${jobId}/cut-review`)}
          className="bg-purple-600 hover:bg-purple-500 px-4 py-2 rounded-lg text-sm transition">
          커팅 검토 →
        </button>
      </div>
    );
  }
  if (job.status === "mesh_done") {
    return (
      <BcSettingsPanel
        jobId={jobId}
        existingBcParams={job.bc_params ?? null}
        onStartSolve={onStartSolve}
      />
    );
  }
  if (job.status === "completed") {
    return (
      <div className="bg-green-900/30 border border-green-700 rounded-xl p-4 mb-6 flex items-center justify-between">
        <p className="font-semibold text-sm">해석 완료</p>
        <button onClick={() => navigate(`/jobs/${jobId}/report`)}
          className="bg-green-600 hover:bg-green-500 px-4 py-2 rounded-lg text-sm transition">
          리포트 보기 →
        </button>
      </div>
    );
  }
  return null;
}

// ── BC Settings Panel ─────────────────────────────────────────────────────────

const MATERIALS = [
  { id: "STEEL_A106_GrB",  label: "Carbon Steel A106 Gr.B",  E: 200000, nu: 0.3, density: 7.85e-9, allowable: 138 },
  { id: "STEEL_A312_TP316", label: "Stainless 316L (A312)",   E: 195000, nu: 0.3, density: 7.99e-9, allowable: 115 },
  { id: "CUSTOM",           label: "사용자 입력",              E: 200000, nu: 0.3, density: 7.85e-9, allowable: 138 },
];

function BcSettingsPanel({ jobId, existingBcParams, onStartSolve }: {
  jobId: string;
  existingBcParams: Record<string, unknown> | null;
  onStartSolve: () => void;
}) {
  const [matId,     setMatId]     = useState(MATERIALS[0].id);
  const [pressure,  setPressure]  = useState(10.0);
  const [allowable, setAllowable] = useState(138.0);
  const [E,         setE]         = useState(200000);
  const [nu,        setNu]        = useState(0.3);
  const [fixedEnd,  setFixedEnd]  = useState<"inlet" | "outlet" | "both">("inlet");
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);

  // Pre-fill from existing bc_params if present
  useState(() => {
    if (!existingBcParams) return;
    const mat = existingBcParams.material as Record<string, number> | undefined;
    if (mat) {
      setAllowable(mat.allowable_stress ?? 138);
      setE(mat.youngs_modulus ?? 200000);
      setNu(mat.poissons_ratio ?? 0.3);
    }
    if (existingBcParams.pressure_mpa) setPressure(existingBcParams.pressure_mpa as number);
    if (existingBcParams.fixed_faces)  setFixedEnd(existingBcParams.fixed_faces as "inlet");
  });

  function onMatChange(id: string) {
    setMatId(id);
    const m = MATERIALS.find(m => m.id === id);
    if (m && id !== "CUSTOM") {
      setAllowable(m.allowable);
      setE(m.E);
      setNu(m.nu);
    }
  }

  async function handleSaveAndSolve() {
    setSaving(true);
    const mat = MATERIALS.find(m => m.id === matId) ?? MATERIALS[0];
    const bc = {
      material: {
        name: matId,
        youngs_modulus: E,
        poissons_ratio: nu,
        density: mat.density,
        allowable_stress: allowable,
      },
      pressure_mpa: pressure,
      fixed_faces: fixedEnd,
      allowable_stress_mpa: allowable,
    };
    await axios.post(`/api/jobs/${jobId}/bc-params`, bc);
    setSaved(true);
    setSaving(false);
    onStartSolve();
  }

  return (
    <div className="bg-orange-900/20 border border-orange-700 rounded-xl p-5 mb-6">
      <h3 className="font-semibold text-sm mb-4">경계조건 / 하중 설정</h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Material */}
        <div className="col-span-2">
          <label className="text-xs text-gray-400 block mb-1">재료</label>
          <select
            value={matId}
            onChange={e => onMatChange(e.target.value)}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm"
          >
            {MATERIALS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        {/* Pressure */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">내압 (MPa)</label>
          <input type="number" value={pressure} step={0.5} min={0}
            onChange={e => setPressure(parseFloat(e.target.value))}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm font-mono" />
        </div>
        {/* Allowable stress */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">허용 응력 (MPa)</label>
          <input type="number" value={allowable} step={1} min={0}
            onChange={e => setAllowable(parseFloat(e.target.value))}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm font-mono" />
        </div>
        {/* Young's modulus */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">탄성계수 E (MPa)</label>
          <input type="number" value={E} step={1000} min={0}
            onChange={e => setE(parseFloat(e.target.value))}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm font-mono" />
        </div>
        {/* Poisson */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">포아송비 ν</label>
          <input type="number" value={nu} step={0.01} min={0} max={0.5}
            onChange={e => setNu(parseFloat(e.target.value))}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm font-mono" />
        </div>
        {/* Fixed end */}
        <div className="col-span-2">
          <label className="text-xs text-gray-400 block mb-1">고정단 (Encastre)</label>
          <div className="flex gap-3">
            {(["inlet", "outlet", "both"] as const).map(v => (
              <label key={v} className="flex items-center gap-1.5 text-sm cursor-pointer">
                <input type="radio" name="fixedEnd" value={v} checked={fixedEnd === v}
                  onChange={() => setFixedEnd(v)} className="accent-orange-500" />
                {v === "inlet" ? "입구만" : v === "outlet" ? "출구만" : "양쪽"}
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between pt-3 border-t border-orange-800/50">
        <p className="text-xs text-gray-500">
          Phase 2(실제 Abaqus) 전까지는 공학식 기반 Mock 결과가 사용됩니다.
        </p>
        <button
          onClick={handleSaveAndSolve}
          disabled={saving}
          className="bg-orange-600 hover:bg-orange-500 px-5 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
        >
          {saving ? "저장 중..." : "저장 후 해석 시작"}
        </button>
      </div>
    </div>
  );
}


// ── Step cards ────────────────────────────────────────────────────────────────

const STEP_ICONS: Record<string, string> = {
  uploaded: "📁",
  geometry_parsed: "📐",
  cut_suggestion: "✂️",
  mesh_done: "🔲",
  completed: "📊",
};

function StepCard({ step, idx, open, onToggle, jobId }: {
  step: HistoryStep; idx: number; open: boolean;
  onToggle: () => void; jobId: string;
}) {
  const icon = STEP_ICONS[step.step] ?? "•";
  const ts = step.timestamp ? new Date(step.timestamp).toLocaleString("ko-KR") : "";

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-gray-800/50 transition"
      >
        <span className="text-lg leading-none">{icon}</span>
        <span className="font-medium text-sm flex-1">{step.label}</span>
        {ts && <span className="text-xs text-gray-500">{ts}</span>}
        <span className={`text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-gray-800">
          <StepContent step={step} jobId={jobId} />
        </div>
      )}
    </div>
  );
}

function StepContent({ step, jobId }: { step: HistoryStep; jobId: string }) {
  switch (step.step) {
    case "uploaded":
      return <UploadedContent data={step.data} />;
    case "geometry_parsed":
      return <GeometryContent data={step.data} />;
    case "cut_suggestion":
      return <CutSuggestionContent data={step.data} />;
    case "mesh_done":
      return <MeshContent data={step.data} jobId={jobId} />;
    case "completed":
      return <AnalysisContent data={step.data} />;
    default:
      return <pre className="text-xs text-gray-400 mt-3">{JSON.stringify(step.data, null, 2)}</pre>;
  }
}

// ── Uploaded ──────────────────────────────────────────────────────────────────
function UploadedContent({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="mt-3 text-sm space-y-1">
      <Row label="파일명" value={String(data.file_name ?? "")} />
    </div>
  );
}

// ── Geometry ──────────────────────────────────────────────────────────────────
function GeometryContent({ data }: { data: Record<string, unknown> }) {
  const geo = data.geometry_params as Record<string, Record<string, number>> | undefined;
  if (!geo) return null;
  const hp = geo.header_pipe ?? {};
  const bp = geo.branch_pipe ?? {};
  const jct = geo.junction ?? {};
  return (
    <div className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
      <Row label="Case 유형" value={String(data.case_type ?? "미설정")} />
      <Row label="Header OD" value={`${((hp.outer_radius ?? 0) * 2000).toFixed(0)} mm`} />
      <Row label="Branch OD" value={`${((bp.outer_radius ?? 0) * 2000).toFixed(0)} mm`} />
      <Row label="접합 각도" value={`${bp.angle_deg ?? "?"}°`} />
      <Row label="Fillet 반경" value={`${((jct.fillet_radius ?? 0) * 1000).toFixed(0)} mm`} />
      <Row label="Junction 중심" value={
        Array.isArray(jct.center)
          ? `(${(jct.center as number[]).map((v: number) => (v * 1000).toFixed(0)).join(", ")}) mm`
          : "—"
      } />
    </div>
  );
}

// ── Cut Suggestion ────────────────────────────────────────────────────────────
function CutSuggestionContent({ data }: { data: Record<string, unknown> }) {
  const sug = data.ai_suggestion as Record<string, unknown> | null;
  const final = data.final_cut as Record<string, unknown> | null;

  return (
    <div className="mt-3 space-y-4">
      {/* Pattern + confidence */}
      {sug?.pattern && (
        <div className="flex gap-3 items-center">
          <span className="text-xs px-2 py-0.5 bg-gray-800 rounded font-mono text-gray-300">
            {String(sug.pattern)}
          </span>
          <ConfidenceBadge value={String(sug.confidence ?? data.confidence ?? "")} />
          {sug.branch_angle_estimate != null && (
            <span className="text-xs text-gray-500">{String(sug.branch_angle_estimate)}°</span>
          )}
        </div>
      )}

      {/* Observations */}
      {sug?.observations && (
        <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg p-3">
          <p className="text-xs text-blue-400 font-medium mb-1">AI 관찰</p>
          <p className="text-xs text-gray-300 leading-relaxed">{String(sug.observations)}</p>
        </div>
      )}

      {/* Visual analysis */}
      {sug?.visual_analysis && typeof sug.visual_analysis === "object" && (
        <div className="bg-gray-800 rounded-lg p-3 space-y-1">
          <p className="text-xs text-gray-500 font-medium mb-2">이미지 분석</p>
          {Object.entries(sug.visual_analysis as Record<string, string>).map(([k, v]) => (
            <div key={k} className="text-xs">
              <span className="text-gray-500">{k.replace(/_/g, " ")}: </span>
              <span className="text-gray-300">{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* Cut planes — AI proposal vs final */}
      <div className="space-y-2">
        <CutPlanesList
          planes={(sug?.cut_planes as unknown[]) ?? []}
          label="AI 제안"
          color="border-blue-800/50"
        />
        {final?.cut_planes && (
          <CutPlanesList
            planes={final.cut_planes as unknown[]}
            label={`사람이 확정 ${data.adjustment_mm ? `(조정 ${data.adjustment_mm}mm)` : "(AI 그대로 승인)"}`}
            color="border-green-800/50"
          />
        )}
      </div>

      {/* Warning */}
      {sug?.warning && (
        <p className="text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-800/50 rounded p-2">
          {String(sug.warning)}
        </p>
      )}
    </div>
  );
}

function CutPlanesList({ planes, label, color }: {
  planes: unknown[]; label: string; color: string;
}) {
  if (!planes?.length) return null;
  return (
    <div className={`border ${color} rounded-lg p-3`}>
      <p className="text-xs text-gray-500 mb-2">{label}</p>
      <div className="space-y-1">
        {planes.map((p: unknown, i: number) => {
          const plane = p as Record<string, unknown>;
          const isBranch = plane.axis === "branch";
          return (
            <div key={i} className="flex gap-2 items-start text-xs">
              <span className={`px-1.5 py-0.5 rounded font-mono text-xs flex-shrink-0 ${
                isBranch ? "bg-orange-900 text-orange-300" : "bg-gray-800 text-gray-300"
              }`}>
                {String(plane.axis)}
              </span>
              <span className="text-gray-300">{String(plane.offset)}mm</span>
              {isBranch && plane.normal && (
                <span className="text-gray-500">
                  normal=({(plane.normal as number[]).map((n: number) => n.toFixed(3)).join(", ")})
                </span>
              )}
              {plane.reason && (
                <span className="text-gray-600 truncate">{String(plane.reason).slice(0, 80)}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Mesh ──────────────────────────────────────────────────────────────────────
function MeshContent({ data, jobId }: { data: Record<string, unknown>; jobId: string }) {
  const mr = data.mesh_result as Record<string, unknown> | undefined;
  const mp = data.mesh_params as Record<string, unknown> | undefined;
  return (
    <div className="mt-3 space-y-3">
      <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
        <Row label="요소 수" value={(mr?.element_count as number | undefined)?.toLocaleString() ?? "—"} />
        <Row label="Seed Size" value={`${mp?.seed_size ?? "—"} mm`} />
        <Row label="최대 종횡비" value={(mr?.max_aspect_ratio as number | undefined)?.toFixed(3) ?? "—"} />
        <Row label="Min Jacobian" value={(mr?.min_jacobian as number | undefined)?.toFixed(3) ?? "—"} />
        <Row label="실행 시간" value={`${mr?.execution_time ?? "—"} s`} />
      </div>
      {data.vtk_url && (
        <a href={`/api/jobs/${jobId}/vtk`} download
          className="inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition">
          ↓ VTK 파일 다운로드
        </a>
      )}
    </div>
  );
}

// ── Analysis ──────────────────────────────────────────────────────────────────
function AnalysisContent({ data }: { data: Record<string, unknown> }) {
  const ar = data.analysis_result as Record<string, unknown> | undefined;
  const report = data.ai_report as string | undefined;

  return (
    <div className="mt-3 space-y-4">
      {ar && (
        <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
          <Row label="최대 Von Mises" value={`${ar.max_mises ?? "—"} MPa`} highlight={!!(ar.safety_factor && (ar.safety_factor as number) < 1)} />
          <Row label="안전율" value={ar.safety_factor ? (ar.safety_factor as number).toFixed(3) : "—"} good={!!(ar.safety_factor && (ar.safety_factor as number) >= 1)} />
          <Row label="최대 변위" value={`${ar.max_displacement ?? "—"} mm`} />
          <Row label="허용 응력" value={`${ar.allowable_stress ?? "—"} MPa`} />
          <Row label="SIF" value={(ar.sif as number | undefined)?.toFixed(3) ?? "—"} />
          <Row label="임계 위치" value={String(ar.max_stress_location ?? "—")} />
        </div>
      )}
      {report && (
        <details className="group">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200 transition">
            AI 리포트 보기 ▾
          </summary>
          <pre className="mt-2 text-xs text-gray-300 whitespace-pre-wrap leading-relaxed font-sans bg-gray-800 rounded-lg p-3 max-h-80 overflow-y-auto">
            {report}
          </pre>
        </details>
      )}
    </div>
  );
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function Row({ label, value, highlight, good }: {
  label: string; value: string; highlight?: boolean; good?: boolean;
}) {
  const cls = highlight ? "text-red-400" : good ? "text-green-400" : "text-gray-300";
  return (
    <>
      <span className="text-gray-500 text-xs">{label}</span>
      <span className={`font-mono text-xs ${cls}`}>{value}</span>
    </>
  );
}

function ConfidenceBadge({ value }: { value: string }) {
  const colors: Record<string, string> = {
    high: "text-green-400 bg-green-900/30",
    medium: "text-yellow-400 bg-yellow-900/30",
    low: "text-red-400 bg-red-900/30",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[value] ?? "text-gray-400 bg-gray-800"}`}>
      {value?.toUpperCase()}
    </span>
  );
}
