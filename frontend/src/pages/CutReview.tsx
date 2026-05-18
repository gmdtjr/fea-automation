import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useJob } from "../hooks/useJob";
import GeometryViewer from "../components/GeometryViewer";
import CutPlaneControl from "../components/CutPlaneControl";
import type { CutSuggestion, CutPlane } from "../types/job";

export default function CutReview() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { job, loading } = useJob(id!, 5000);
  const [suggestion, setSuggestion] = useState<CutSuggestion | null>(null);
  const [pending, setPending] = useState(false);
  const [approving, setApproving] = useState(false);
  const [activePlanes, setActivePlanes] = useState<CutPlane[]>([]);

  useEffect(() => {
    if (!id) return;
    axios.get(`/api/jobs/${id}/cut-suggestion`).then(({ data }) => {
      if (data.pending) {
        setPending(true);
        return;
      }
      if (data.suggestion) {
        setSuggestion(data.suggestion);
        setActivePlanes(data.suggestion.cut_planes ?? []);
      }
    });
  }, [id]);

  // Poll until AI suggestion arrives
  useEffect(() => {
    if (!pending) return;
    const interval = setInterval(async () => {
      const { data } = await axios.get(`/api/jobs/${id}/cut-suggestion`);
      if (!data.pending && data.suggestion) {
        setSuggestion(data.suggestion);
        setActivePlanes(data.suggestion.cut_planes ?? []);
        setPending(false);
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [pending, id]);

  async function handleApprove(planes: CutPlane[], adjustmentMm: number) {
    setApproving(true);
    try {
      await axios.post(`/api/jobs/${id}/cut-approve`, {
        cut_planes: planes,
        adjustment_mm: adjustmentMm,
      });
      navigate(`/jobs/${id}`);
    } finally {
      setApproving(false);
    }
  }

  if (loading || !job) return <div className="p-8 text-gray-400">Loading...</div>;

  const CONFIDENCE_COLOR: Record<string, string> = {
    high: "text-green-400",
    medium: "text-yellow-400",
    low: "text-red-400",
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-800 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(`/jobs/${id}`)} className="text-gray-400 hover:text-white text-sm">
            ← 뒤로
          </button>
          <h2 className="font-semibold">커팅 위치 검토 — {job.file_name}</h2>
        </div>
        {suggestion && (
          <div className="flex items-center gap-3 text-sm">
            {suggestion.pattern && suggestion.pattern !== "unknown" && (
              <span className="px-2 py-0.5 bg-gray-800 rounded text-xs text-gray-300 font-mono">
                {suggestion.pattern}
              </span>
            )}
            <span className="text-gray-400">신뢰도:</span>
            <span className={`font-medium ${CONFIDENCE_COLOR[suggestion.confidence] ?? "text-gray-400"}`}>
              {suggestion.confidence.toUpperCase()}
            </span>
          </div>
        )}
      </div>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* 3D Viewer */}
        <div className="flex-1 bg-gray-950">
          <GeometryViewer
            jobId={id!}
            geometryParams={job.geometry_params}
            cutPlanes={activePlanes}
            highlightCut={true}
          />
        </div>

        {/* Side panel */}
        <div className="w-96 border-l border-gray-800 p-6 overflow-y-auto bg-gray-950">
          {pending ? (
            <div className="text-center py-12">
              <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
              <p className="text-gray-400">AI가 커팅 위치를 분석 중입니다...</p>
            </div>
          ) : suggestion ? (
            <>
              {/* Pattern classification card */}
              {suggestion.pattern && (
                <PatternCard suggestion={suggestion} />
              )}

              {/* Observations + visual analysis */}
              {(suggestion.observations || (suggestion as any).visual_analysis) && (
                <div className="bg-blue-900/20 border border-blue-800 rounded-lg p-3 mb-4 space-y-2">
                  <p className="text-xs text-blue-400 font-medium">AI 형상 분석</p>
                  {suggestion.observations && (
                    <p className="text-xs text-gray-300 leading-relaxed">{suggestion.observations}</p>
                  )}
                  {(suggestion as any).visual_analysis && (
                    <div className="text-xs space-y-1 pt-1 border-t border-blue-800/50">
                      {Object.entries((suggestion as any).visual_analysis).map(([k, v]) => (
                        <div key={k}>
                          <span className="text-blue-500">{k.replace(/_/g," ")}: </span>
                          <span className="text-gray-400">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Warning */}
              {suggestion.warning && (
                <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-3 mb-4 text-sm text-yellow-300">
                  {suggestion.warning}
                </div>
              )}

              {/* Human review required */}
              {suggestion.needs_human_review && activePlanes.length === 0 ? (
                <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4">
                  <p className="text-red-400 font-semibold text-sm mb-1">수동 커팅 위치 지정 필요</p>
                  <p className="text-xs text-gray-400">
                    AI가 형상을 분류하지 못했거나 신뢰도가 낮습니다.
                    아래에서 커팅 평면을 직접 추가하세요.
                  </p>
                </div>
              ) : null}

              <h3 className="font-semibold mb-4">커팅 평면 조정</h3>
              <CutPlaneControl
                initialPlanes={activePlanes}
                bbox={job.geometry_params?.bounding_box ?? null}
                onApprove={handleApprove}
                disabled={approving}
              />
              {approving && (
                <p className="text-center text-gray-400 text-sm mt-4 animate-pulse">
                  메시 생성 시작 중...
                </p>
              )}
            </>
          ) : (
            <p className="text-gray-400 text-sm">커팅 제안 데이터가 없습니다.</p>
          )}
        </div>
      </div>
    </div>
  );
}

const PATTERN_ICONS: Record<string, string> = {
  lateral_tee:   "⟋",
  t_joint_90:    "⊤",
  y_joint:       "Y",
  multi_branch:  "⋔",
  elbow:         "⌒",
  straight_pipe: "—",
  unknown:       "?",
};

function PatternCard({ suggestion }: { suggestion: CutSuggestion }) {
  const pattern     = suggestion.pattern ?? "unknown";
  const description = suggestion.pattern_description ?? "";
  const icon        = PATTERN_ICONS[pattern] ?? "?";
  const isUnknown   = pattern === "unknown";

  return (
    <div className={`rounded-lg p-3 mb-4 border ${
      isUnknown
        ? "bg-red-900/20 border-red-800"
        : "bg-gray-800 border-gray-700"
    }`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg leading-none">{icon}</span>
        <span className="text-sm font-semibold text-gray-200">{pattern}</span>
        {suggestion.branch_angle_estimate != null && (
          <span className="text-xs text-gray-500 ml-auto">{suggestion.branch_angle_estimate}°</span>
        )}
      </div>
      <p className="text-xs text-gray-400">{description}</p>
      {suggestion.param_discrepancy && (
        <p className="text-xs text-yellow-400 mt-1">⚠ {suggestion.param_discrepancy}</p>
      )}
      {suggestion.anomalies && (
        <p className="text-xs text-orange-400 mt-1">⚡ {suggestion.anomalies}</p>
      )}
    </div>
  );
}
