export type JobStatus =
  | "pending"
  | "geometry_parsed"
  | "awaiting_cut_review"
  | "meshing"
  | "mesh_done"
  | "solving"
  | "completed"
  | "failed";

export interface Job {
  id: string;
  file_name: string;
  case_type: string | null;
  status: JobStatus;
  geometry_params: GeometryParams | null;
  mesh_params: Record<string, unknown> | null;
  bc_params: BcParams | null;
  mesh_result: MeshResult | null;
  analysis_result: AnalysisResult | null;
  ai_report: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BcMaterial {
  name: string;
  youngs_modulus: number;
  poissons_ratio: number;
  density: number;
  allowable_stress: number;
}

export interface BcParams {
  material: BcMaterial;
  pressure_mpa: number;
  fixed_faces: "inlet" | "outlet" | "both";
  allowable_stress_mpa: number;
}

export interface GeometryParams {
  file_type: string;
  header_pipe: { outer_radius: number; inner_radius: number; length: number };
  branch_pipe: { outer_radius: number; inner_radius: number; angle_deg: number };
  junction: { center: [number, number, number]; fillet_radius: number };
  bounding_box: { x: [number, number]; y: [number, number]; z: [number, number] };
  seed_size_recommendation: number;
}

export interface MeshResult {
  status: string;
  element_count: number;
  max_aspect_ratio: number;
  min_jacobian: number;
  vtk_file: string;
  execution_time: number;
}

export interface AnalysisResult {
  status: string;
  job_name: string;
  max_mises: number;
  max_displacement: number;
  max_stress_location: string;
  result_file: string;
}

export interface CutPlane {
  axis: "X" | "Y" | "Z" | "branch";
  offset: number;          // axis-aligned: mm from origin; branch: mm along branch axis
  normal?: [number, number, number];   // only for axis="branch"
  point?: [number, number, number];    // only for axis="branch"
  angle_deg?: number;                  // only for axis="branch"
  reason?: string;
}

export interface CutSuggestion {
  cut_planes: CutPlane[];
  confidence: "high" | "medium" | "low";
  warning: string | null;
  observations?: string;
  pattern?: string;
  pattern_description?: string;
  branch_angle_estimate?: number | null;
  param_discrepancy?: string | null;
  anomalies?: string | null;
  needs_human_review?: boolean;
}
