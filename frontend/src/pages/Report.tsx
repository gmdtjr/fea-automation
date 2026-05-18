import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import GeometryViewer from "../components/GeometryViewer";
import MeshViewer from "../components/MeshViewer";
import { useJob } from "../hooks/useJob";

interface ReportData {
  job_id: string;
  file_name: string;
  case_type: string;
  generated_at: string;
  geometry_summary: {
    header_OD_mm: number;
    branch_OD_mm: number;
    branch_angle_deg: number;
  };
  mesh_summary: {
    element_count: number;
    max_aspect_ratio: number;
    min_jacobian: number;
    execution_time_s: number;
  };
  analysis_summary: {
    max_mises_MPa: number;
    max_displacement_mm: number;
    critical_location: string;
    allowable_stress?: number;
    safety_factor?: number;
    sif?: number;
    sigma_hoop_header_mpa?: number;
    pressure_mpa?: number;
  };
  ai_report: string | null;
}

export default function Report() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { job } = useJob(id!, 0);
  const [report, setReport] = useState<ReportData | null>(null);
  const [viewTab, setViewTab] = useState<"mesh" | "geometry">("mesh");
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!id) return;
    axios.get(`/api/jobs/${id}/results`).then(({ data }) => setReport(data));
  }, [id]);

  // Close fullscreen on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const vtkUrl = job?.mesh_result?.vtk_file ? `/api/jobs/${id}/vtk` : null;

  const viewer3D = (height: string) => (
    <div className="bg-gray-900 rounded-xl overflow-hidden flex flex-col" style={{ height }}>
      <div className="flex items-center border-b border-gray-800 flex-shrink-0">
        {(["mesh", "geometry"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setViewTab(tab)}
            className={`flex-1 py-2 text-xs font-medium transition ${
              viewTab === tab ? "text-white border-b-2 border-blue-500" : "text-gray-500 hover:text-gray-300"
            }`}
          >
            {tab === "mesh" ? "메시 결과" : "형상 (STL)"}
          </button>
        ))}
        <button
          onClick={() => setFullscreen((v) => !v)}
          className="px-3 py-2 text-gray-500 hover:text-white transition text-xs"
          title="전체 화면"
        >
          {fullscreen ? "✕ 닫기" : "⛶ 전체화면"}
        </button>
      </div>
      <div className="flex-1 min-h-0">
        {viewTab === "mesh" ? (
          <MeshViewer vtkUrl={vtkUrl} />
        ) : job?.geometry_params ? (
          <GeometryViewer jobId={id!} geometryParams={job.geometry_params} />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">형상 데이터 없음</div>
        )}
      </div>
    </div>
  );

  const summaryCards = (
    <>
      {report && (
        <>
          <SummaryCard title="형상" rows={[
            ["Header OD", `${report.geometry_summary.header_OD_mm} mm`],
            ["Branch OD", `${report.geometry_summary.branch_OD_mm} mm`],
            ["접합 각도", `${report.geometry_summary.branch_angle_deg}°`],
          ]} />
          <SummaryCard title="메시" rows={[
            ["요소 수", report.mesh_summary.element_count?.toLocaleString()],
            ["최대 종횡비", report.mesh_summary.max_aspect_ratio?.toFixed(3)],
            ["메시 시간", `${report.mesh_summary.execution_time_s} s`],
          ]} />
          <AnalysisCard analysis={report.analysis_summary} />
        </>
      )}
    </>
  );

  return (
    <>
      {/* Fullscreen overlay */}
      {fullscreen && (
        <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
          {/* Fullscreen header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-gray-800 flex-shrink-0">
            <div>
              <span className="font-semibold text-sm">{report?.file_name ?? job?.file_name}</span>
              {report && (
                <span className="text-gray-500 text-xs ml-3">
                  {new Date(report.generated_at).toLocaleString("ko-KR")}
                </span>
              )}
            </div>
            <button
              onClick={() => setFullscreen(false)}
              className="text-gray-400 hover:text-white text-sm px-3 py-1 rounded border border-gray-700 hover:border-gray-500 transition"
            >
              ✕ 닫기 (Esc)
            </button>
          </div>

          {/* Fullscreen body */}
          <div className="flex flex-1 min-h-0 gap-4 p-4">
            {/* Viewer — takes most space */}
            <div className="flex-1 min-w-0 flex flex-col bg-gray-900 rounded-xl overflow-hidden">
              <div className="flex items-center border-b border-gray-800 flex-shrink-0">
                {(["mesh", "geometry"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setViewTab(tab)}
                    className={`flex-1 py-2.5 text-xs font-medium transition ${
                      viewTab === tab ? "text-white border-b-2 border-blue-500" : "text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    {tab === "mesh" ? "메시 결과" : "형상 (STL)"}
                  </button>
                ))}
              </div>
              <div className="flex-1 min-h-0">
                {viewTab === "mesh" ? (
                  <MeshViewer vtkUrl={vtkUrl} />
                ) : job?.geometry_params ? (
                  <GeometryViewer jobId={id!} geometryParams={job.geometry_params} />
                ) : null}
              </div>
            </div>

            {/* Right panel: summary + AI report */}
            <div className="w-80 flex-shrink-0 flex flex-col gap-4 overflow-y-auto">
              {summaryCards}
              {report?.ai_report && (
                <div className="bg-gray-900 rounded-xl p-4">
                  <h3 className="font-semibold text-xs text-gray-500 uppercase tracking-wider mb-3">AI 해석</h3>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed font-sans">
                    {report.ai_report}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Normal page */}
      <div className="min-h-screen p-8 max-w-5xl mx-auto">
        <button onClick={() => navigate(`/jobs/${id}`)} className="text-gray-400 hover:text-white mb-6 text-sm">
          ← 뒤로
        </button>
        <h2 className="text-2xl font-bold mb-1">해석 결과 리포트</h2>
        {report && (
          <p className="text-gray-400 text-sm mb-8">
            {report.file_name} — {new Date(report.generated_at).toLocaleString("ko-KR")}
          </p>
        )}

        <div className="grid grid-cols-2 gap-6 mb-8">
          {viewer3D("340px")}
          <div className="space-y-4">{summaryCards}</div>
        </div>

        {report?.ai_report && (
          <div className="bg-gray-900 rounded-xl p-6">
            <h3 className="font-semibold mb-4 text-gray-300">AI 엔지니어링 해석</h3>
            <pre className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed font-sans">
              {report.ai_report}
            </pre>
          </div>
        )}
      </div>
    </>
  );
}

function SummaryCard({ title, rows }: { title: string; rows: [string, string | number | undefined][] }) {
  return (
    <div className="bg-gray-900 rounded-xl p-4">
      <h4 className="text-xs text-gray-500 uppercase tracking-wider mb-3">{title}</h4>
      <div className="space-y-1.5">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between text-sm">
            <span className="text-gray-400">{label}</span>
            <span className="font-mono text-gray-200">{value ?? "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalysisCard({ analysis }: { analysis: ReportData["analysis_summary"] }) {
  const sf = analysis.safety_factor;
  const allowable = analysis.allowable_stress ?? 138;
  const verdict = sf != null ? (sf >= 1.0 ? "OK" : "NG") : null;
  const verdictColor = verdict === "OK" ? "text-green-400" : verdict === "NG" ? "text-red-400" : "text-gray-400";

  return (
    <div className="bg-gray-900 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs text-gray-500 uppercase tracking-wider">해석</h4>
        {verdict && (
          <span className={`text-sm font-bold ${verdictColor}`}>{verdict}</span>
        )}
      </div>
      <div className="space-y-1.5 text-sm">
        <Row label="최대 Von Mises" value={`${analysis.max_mises_MPa} MPa`} highlight={verdict === "NG"} />
        <Row label="허용 응력" value={`${allowable} MPa`} />
        {sf != null && (
          <Row
            label="안전율"
            value={sf.toFixed(3)}
            highlight={sf < 1.0}
            good={sf >= 1.0}
          />
        )}
        <Row label="최대 변위" value={`${analysis.max_displacement_mm} mm`} />
        {analysis.sif != null && <Row label="응력 집중계수 (SIF)" value={analysis.sif.toFixed(3)} />}
        {analysis.sigma_hoop_header_mpa != null && (
          <Row label="기본 Hoop 응력" value={`${analysis.sigma_hoop_header_mpa} MPa`} />
        )}
        {analysis.pressure_mpa != null && <Row label="내압" value={`${analysis.pressure_mpa} MPa`} />}
        <div className="pt-1 border-t border-gray-800">
          <span className="text-gray-500">임계 위치 </span>
          <span className="text-gray-200 text-xs">{analysis.critical_location}</span>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, highlight, good }: {
  label: string; value: string;
  highlight?: boolean; good?: boolean;
}) {
  const cls = highlight ? "text-red-400 font-bold" : good ? "text-green-400 font-bold" : "text-gray-200";
  return (
    <div className="flex justify-between">
      <span className="text-gray-400">{label}</span>
      <span className={`font-mono ${cls}`}>{value}</span>
    </div>
  );
}
