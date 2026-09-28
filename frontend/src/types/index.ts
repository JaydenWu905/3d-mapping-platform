// 与后端 FastAPI 模型一一对应的类型（已针对真实响应验证过字段名）。

export type StageKey = 'pose' | 'surface' | 'distance';
export type StageStatus = 'waiting' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';
export type BackendStatus = 'ready' | 'experimental' | 'disabled';

/** SSE 事件里 stage 字段是普通 string，这里做运行时校验后收窄成 StageKey。 */
const STAGE_KEYS: readonly string[] = ['pose', 'surface', 'distance'];
export function isStageKey(s: string): s is StageKey {
  return STAGE_KEYS.includes(s);
}

export interface BackendDef {
  id: string;
  display_name: string;
  status: BackendStatus;
  input_modalities: string[];
  preview_types: string[];
  description: string;
  home_url: string;
  capabilities: Record<string, unknown>;
  unavailable_reason: string;
}

export interface BackendsResponse {
  stages: StageKey[];
  groups: Record<StageKey, BackendDef[]>;
}

export interface DatasetInfo {
  id: string;
  name: string;
  description: string;
  input_manifest?: Record<string, unknown>;
}

export interface ArtifactInfo {
  artifact_id: string;
  role: 'preview' | 'data' | 'trajectory';
  path: string; // 服务器端相对路径，仅用于展示；真正取文件一律经过 artifact_id
  content_type: string;
  download?: boolean;
  note?: string;
}

export interface Manifest {
  schema_version: string;
  job_id: string;
  stage: string;
  backend: string;
  status: string;
  runtime_sec: number;
  frame_id: string;
  unit: string;
  metrics: Record<string, unknown>;
  artifacts: ArtifactInfo[];
  backend_details?: Record<string, unknown>;
}

export interface StageDetail {
  stage: string;
  backend: string;
  backend_display: string;
  backend_status: string;
  status: StageStatus;
  phase: string;
  progress: number;
  current: number;
  total: number;
  unit: string;
  message: string;
  elapsed_sec: number;
  started_at: string | null;
  finished_at: string | null;
  manifest: Manifest | null;
  can_run: boolean;
  run_blocked_reason: string;
}

export interface JobDetail {
  job_id: string;
  created_at: string;
  status: string;
  dataset: string;
  backends: Partial<Record<StageKey, string>>;
  preview_job: boolean;
  fail_stage: string | null;
  stages: Record<StageKey, StageDetail>;
}

export interface JobSummary {
  job_id: string;
  created_at: string;
  status: string;
  dataset: string;
  preview_job: boolean;
  stages: Partial<Record<StageKey, string>>;
}

// ---- SSE 增量事件 ----

export type JobStatusEvent = { status: string };

export type StageStatusEvent = {
  stage: string;
  status?: string;
  message?: string;
};

export type StageProgressEvent = {
  stage: string;
  status?: string;
  phase?: string;
  progress?: number;
  current?: number;
  total?: number;
  unit?: string;
  message?: string;
  elapsed_sec?: number;
};

export type StageResultEvent = { stage: string; status: string };

export type SnapshotEvent = JobDetail;

// ---- 预览数据格式（由 make_demo_data / mock runner 生成）----

export interface TrajectoryPoint {
  x: number;
  y: number;
  z: number;
  qx: number;
  qy: number;
  qz: number;
  qw: number;
}

export interface TrajectoryData {
  frame_count: number;
  points: TrajectoryPoint[];
}

export interface GradientArrow {
  x: number;
  y: number;
  dx: number;
  dy: number;
}

export interface GradientPlane {
  rows: number;
  cols: number;
  magnitude_max: number;
  arrows: GradientArrow[];
}
