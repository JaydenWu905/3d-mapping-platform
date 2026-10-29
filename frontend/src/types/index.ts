// 与后端 FastAPI 模型一一对应的类型（已针对真实响应验证过字段名）。

export type StageKey = 'pose' | 'surface' | 'distance';
export type StageStatus = 'waiting' | 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'not_integrated';
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
  progress_run_id?: string;
  progress_started_at?: string;
  progress_seq?: number;
  progress_scope?: 'input' | 'step' | 'stage' | 'none';
  selected_frames?: number;
  visited_frames?: number;
  matched_frames?: number;
  fused_frames?: number;
  skipped_frames?: number;
  counter_updated_at?: string;
  counter_age_sec?: number;
  lidar_published?: number;
  lidar_total?: number;
  imu_published?: number;
  imu_total?: number;
  input_updated_at?: string | null;
  started_at: string | null;
  finished_at: string | null;
  manifest: Manifest | null;
  can_run: boolean;
  run_blocked_reason: string;
}

export interface JobDetail {
  job_id: string;
  name?: string | null;
  device_config?: { id: string; version: string; sha256?: string | null; snapshot: string; effective_params: string };
  created_at: string;
  status: string;
  dataset: string;
  backends: Partial<Record<StageKey, string>>;
  preview_job: boolean;
  requested_stages: StageKey[];
  pose_reuse?: { label: string; source_job_id: string; sha256: string; glim_executed_this_job: boolean };
  validation_scope?: string;
  run_mode?: 'full' | 'short';
  run_scope?: { pose: string; surface_start_frame: number; surface_end_frame: number | null };
  fail_stage: string | null;
  stages: Record<StageKey, StageDetail>;
}

export interface JobSummary {
  job_id: string;
  name?: string | null;
  created_at: string;
  status: string;
  dataset: string;
  preview_job: boolean;
  stages: Partial<Record<StageKey, string>>;
  // 列表接口当前不返回这两个字段；旧任务按 stages 中的 not_integrated 回退判断。
  backends?: Partial<Record<StageKey, string>>;
  requested_stages?: StageKey[];
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
  progress_run_id?: string;
  progress_started_at?: string;
  progress_seq?: number;
  progress_scope?: 'input' | 'step' | 'stage' | 'none';
  selected_frames?: number;
  visited_frames?: number;
  matched_frames?: number;
  fused_frames?: number;
  skipped_frames?: number;
  counter_updated_at?: string;
  counter_age_sec?: number;
  lidar_published?: number;
  lidar_total?: number;
  imu_published?: number;
  imu_total?: number;
  input_updated_at?: string | null;
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

// ---- 距离场切片 / 点云元信息 ----
// 由 backend/scripts/esdf_postprocess.py 写入 preview/slices_meta.json，并整份塞进
// manifest.metrics.slices_meta，前端无需额外请求即可展示物理含义。
// 兼容老格式：slices_meta 直接是 { xy: {...}, xz: {...}, yz: {...} }。

export type AxisRange = [number, number];

export interface SlicePlaneMeta {
  file?: string;
  u_axis?: string;
  v_axis?: string;
  normal_axis?: string;
  u_range?: AxisRange;
  v_range?: AxisRange;
  image_size_px?: [number, number];
  pixel_size_m?: number;
  distance_range?: AxisRange; // 图例范围（固定 ±1.5 m）
  distance_range_observed?: AxisRange; // 实际采样到的距离极值
  center_m?: number; // 切片法向位置
  half_thickness_m?: number;
  thickness_m?: number;
  sampled_points?: number;
  unit?: string;
  unknown_color?: string;
  preview_abs_distance_max_m?: number;
  image_orientation?: string;
}

export interface EsdfWebPreviewMeta {
  file?: string;
  format?: string;
  properties?: string[];
  point_count?: number;
  source_point_count?: number;
  downsample_ratio?: number;
  distance_range?: AxisRange;
  distance_range_observed?: AxisRange;
  size_bytes?: number;
  bounds_m?: Record<string, AxisRange>;
  max_points?: number;
  unit?: string;
}

export interface SlicesMeta {
  schema_version?: string;
  unit?: string;
  image_resolution_px?: number;
  distance_legend_range_m?: AxisRange;
  preview_abs_distance_max_m?: number;
  bounds_m?: Record<string, AxisRange>;
  planes?: Record<string, SlicePlaneMeta>;
  web_preview?: EsdfWebPreviewMeta;
}
