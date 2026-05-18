import { useState } from "react";
import type { CutPlane } from "../types/job";

interface Props {
  initialPlanes: CutPlane[];
  bbox: { x: [number, number]; y: [number, number]; z: [number, number] } | null;
  onApprove: (planes: CutPlane[], adjustmentMm: number) => void;
  disabled?: boolean;
}

export default function CutPlaneControl({ initialPlanes, bbox, onApprove, disabled }: Props) {
  const [planes, setPlanes] = useState<CutPlane[]>(
    initialPlanes.length > 0 ? initialPlanes : [{ axis: "X", offset: 0 }]
  );
  const [originalOffset] = useState(initialPlanes[0]?.offset ?? 0);

  function updatePlane(idx: number, field: keyof CutPlane, value: string | number) {
    setPlanes((prev) => prev.map((p, i) => (i === idx ? { ...p, [field]: value } : p)));
  }

  function addPlane() {
    setPlanes((prev) => [...prev, { axis: "X", offset: 0 }]);
  }

  function removePlane(idx: number) {
    setPlanes((prev) => prev.filter((_, i) => i !== idx));
  }

  function handleApprove() {
    const adjustment = planes[0] ? Math.abs(planes[0].offset - originalOffset) : 0;
    onApprove(planes, adjustment);
  }

  function axisRange(axis: string): [number, number] {
    if (!bbox) return [-2000, 4000];
    const map: Record<string, [number, number]> = { X: bbox.x, Y: bbox.y, Z: bbox.z };
    return map[axis] ?? [-2000, 4000];
  }

  return (
    <div className="space-y-4">
      {planes.map((plane, idx) => {
        if (plane.axis === "branch") {
          return <BranchPlaneCard key={idx} plane={plane} idx={idx} disabled={disabled} />;
        }

        const [min, max] = axisRange(plane.axis);
        return (
          <div key={idx} className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-300">커팅 평면 {idx + 1}</span>
              {planes.length > 1 && !disabled && (
                <button onClick={() => removePlane(idx)} className="text-red-400 text-xs hover:text-red-300">
                  삭제
                </button>
              )}
            </div>
            <div className="flex gap-3 items-center">
              <label className="text-xs text-gray-400 w-6">축</label>
              <select
                value={plane.axis}
                onChange={(e) => updatePlane(idx, "axis", e.target.value)}
                disabled={disabled}
                className="bg-gray-700 rounded px-2 py-1 text-sm"
              >
                {["X", "Y", "Z"].map((ax) => <option key={ax}>{ax}</option>)}
              </select>
            </div>
            <div className="flex gap-3 items-center">
              <label className="text-xs text-gray-400 w-6">위치</label>
              <input
                type="range"
                min={min}
                max={max}
                step={1}
                value={plane.offset}
                onChange={(e) => updatePlane(idx, "offset", parseFloat(e.target.value))}
                disabled={disabled}
                className="flex-1 accent-blue-500"
              />
              <span className="w-20 text-right font-mono text-sm">{plane.offset.toFixed(1)} mm</span>
            </div>
            {plane.reason && (
              <p className="text-xs text-gray-500 italic">{plane.reason}</p>
            )}
          </div>
        );
      })}

      <div className="flex gap-3">
        <button
          onClick={addPlane}
          disabled={disabled}
          className="flex-1 border border-gray-600 rounded-lg py-2 text-sm hover:bg-gray-800 transition disabled:opacity-40"
        >
          + 커팅 평면 추가
        </button>
        <button
          onClick={handleApprove}
          disabled={disabled}
          className="flex-1 bg-blue-600 hover:bg-blue-500 rounded-lg py-2 text-sm font-medium transition disabled:opacity-40"
        >
          승인 및 메시 생성
        </button>
      </div>
    </div>
  );
}

function BranchPlaneCard({ plane, idx, disabled }: { plane: CutPlane; idx: number; disabled?: boolean }) {
  const n = plane.normal ?? [0, 1, 0];
  const p = plane.point ?? [0, 0, 0];
  return (
    <div className="bg-orange-950/40 border border-orange-700/50 rounded-lg p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs px-1.5 py-0.5 bg-orange-700 rounded text-orange-100 font-mono">Branch 축 수직</span>
        <span className="text-sm font-medium text-gray-300">커팅 평면 {idx + 1}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono text-gray-400">
        <span>법선 벡터</span>
        <span className="text-orange-300">({n[0].toFixed(3)}, {n[1].toFixed(3)}, {n[2].toFixed(3)})</span>
        <span>기준점</span>
        <span className="text-orange-300">({p[0].toFixed(0)}, {p[1].toFixed(0)}, {p[2].toFixed(0)}) mm</span>
        <span>Branch 거리</span>
        <span className="text-orange-300">{plane.offset.toFixed(1)} mm</span>
        {plane.angle_deg != null && <>
          <span>Branch 각도</span>
          <span className="text-orange-300">{plane.angle_deg}°</span>
        </>}
      </div>
      {plane.reason && (
        <p className="text-xs text-gray-500 italic">{plane.reason}</p>
      )}
      <p className="text-xs text-orange-400/70">
        이 평면은 branch 축에 수직인 oblique plane입니다 — 뷰어에서 주황색으로 표시됩니다.
      </p>
    </div>
  );
}
