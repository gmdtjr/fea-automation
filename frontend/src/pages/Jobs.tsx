import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useJobs } from "../hooks/useJob";
import type { Job } from "../types/job";

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

export default function Jobs() {
  const { jobs, loading, refresh } = useJobs();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const { data } = await axios.post("/api/jobs/upload", fd);
    refresh();
    navigate(`/jobs/${data.job_id}`);
  }

  function toggleSelect(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === jobs.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(jobs.map((j) => j.id)));
    }
  }

  async function deleteSelected() {
    setDeleting(true);
    try {
      await Promise.all([...selected].map((id) => axios.delete(`/api/jobs/${id}`)));
      setSelected(new Set());
      refresh();
    } finally {
      setDeleting(false);
      setShowDeleteModal(false);
    }
  }

  function rowClick(job: Job, e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest("[data-no-nav]")) return;
    if (job.status === "awaiting_cut_review") navigate(`/jobs/${job.id}/cut-review`);
    else if (job.status === "completed") navigate(`/jobs/${job.id}/report`);
    else navigate(`/jobs/${job.id}`);
  }

  const allChecked = jobs.length > 0 && selected.size === jobs.length;
  const someChecked = selected.size > 0 && selected.size < jobs.length;
  const selectedJobs = jobs.filter((j) => selected.has(j.id));

  return (
    <div className="min-h-screen p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold">FEA Automation</h1>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <button
              onClick={() => setShowDeleteModal(true)}
              className="flex items-center gap-2 bg-red-700 hover:bg-red-600 px-4 py-2 rounded-lg text-sm font-medium transition"
            >
              <span>삭제</span>
              <span className="bg-red-900 text-red-200 text-xs px-1.5 py-0.5 rounded-full">
                {selected.size}
              </span>
            </button>
          )}
          <button
            onClick={() => fileRef.current?.click()}
            className="bg-blue-600 hover:bg-blue-700 px-5 py-2 rounded-lg font-medium transition"
          >
            + Upload File
          </button>
        </div>
        <input ref={fileRef} type="file" accept=".stp,.step,.x_t,.x_b"
          className="hidden" onChange={handleUpload} />
      </div>

      {/* Delete confirmation modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-[440px]">
            <h3 className="font-semibold text-lg mb-3">
              {selected.size}개 Job 삭제
            </h3>
            <div className="max-h-48 overflow-y-auto mb-4 space-y-1">
              {selectedJobs.map((job) => (
                <div key={job.id} className="flex items-center gap-2 text-sm">
                  <span className={`px-1.5 py-0.5 rounded text-xs ${STATUS_COLOR[job.status] ?? "bg-gray-600"}`}>
                    {job.status}
                  </span>
                  <span className="font-mono text-gray-300 truncate">{job.file_name}</span>
                </div>
              ))}
            </div>
            <p className="text-gray-500 text-xs mb-6">
              관련 파일(VTK, STL)과 커팅 이력도 함께 삭제됩니다. 복구 불가.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteModal(false)}
                className="flex-1 border border-gray-600 rounded-lg py-2 text-sm hover:bg-gray-800 transition"
              >
                취소
              </button>
              <button
                onClick={deleteSelected}
                disabled={deleting}
                className="flex-1 bg-red-700 hover:bg-red-600 rounded-lg py-2 text-sm font-medium transition disabled:opacity-50"
              >
                {deleting ? `삭제 중... (${selected.size}개)` : `${selected.size}개 삭제`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Job list */}
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : jobs.length === 0 ? (
        <div className="text-center py-24 text-gray-500">
          <p className="text-xl">No jobs yet.</p>
          <p className="mt-2 text-sm">Upload a STEP or Parasolid X_T file to start.</p>
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-800">
              <th className="pb-3 pr-3 w-8" data-no-nav="1">
                <input
                  type="checkbox"
                  checked={allChecked}
                  ref={(el) => { if (el) el.indeterminate = someChecked; }}
                  onChange={toggleAll}
                  className="accent-blue-500 cursor-pointer"
                />
              </th>
              <th className="pb-3 pr-4">File</th>
              <th className="pb-3 pr-4">Case</th>
              <th className="pb-3 pr-4">Status</th>
              <th className="pb-3 pr-4">Elements</th>
              <th className="pb-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const isSelected = selected.has(job.id);
              return (
                <tr
                  key={job.id}
                  onClick={(e) => rowClick(job, e)}
                  className={`border-b border-gray-800 cursor-pointer transition ${
                    isSelected ? "bg-blue-950/40" : "hover:bg-gray-900"
                  }`}
                >
                  <td className="py-3 pr-3" data-no-nav="1">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {}}
                      onClick={(e) => toggleSelect(job.id, e)}
                      className="accent-blue-500 cursor-pointer"
                    />
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-gray-300">{job.file_name}</td>
                  <td className="py-3 pr-4 uppercase text-xs text-gray-400">{job.case_type ?? "—"}</td>
                  <td className="py-3 pr-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOR[job.status] ?? "bg-gray-600"}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="py-3 pr-4 text-gray-300">
                    {job.mesh_result?.element_count?.toLocaleString() ?? "—"}
                  </td>
                  <td className="py-3 text-gray-400 text-xs">
                    {job.created_at ? new Date(job.created_at).toLocaleString("ko-KR") : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Bottom selection summary */}
      {selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-gray-800 border border-gray-600 rounded-full px-6 py-3 flex items-center gap-4 shadow-xl">
          <span className="text-sm text-gray-300">
            <span className="font-bold text-white">{selected.size}개</span> 선택됨
          </span>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-gray-400 hover:text-white transition"
          >
            선택 해제
          </button>
          <button
            onClick={() => setShowDeleteModal(true)}
            className="text-xs text-red-400 hover:text-red-300 transition font-medium"
          >
            삭제
          </button>
        </div>
      )}
    </div>
  );
}
