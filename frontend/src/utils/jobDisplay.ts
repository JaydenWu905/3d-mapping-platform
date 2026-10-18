import type { JobSummary, StageKey } from '../types';

// ----------------------------------------------------------------------
// 任务展示语义（仅前端派生，不写入后端业务字段）
// ----------------------------------------------------------------------

export const STAGE_ORDER: readonly StageKey[] = ['pose', 'surface', 'distance'];

/** 页面统一使用的中文阶段名。 */
export const STAGE_NAMES: Record<StageKey, string> = {
  pose: '位姿估计',
  surface: '表面重建',
  distance: '距离场',
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  waiting: '等待中',
  queued: 'GPU 排队中',
  not_integrated: '未请求',
  running: '运行中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export type JobStatusFilter = 'all' | 'running' | 'completed' | 'failed' | 'cancelled' | 'created';

export const JOB_STATUS_FILTERS: { value: JobStatusFilter; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'created', label: '已创建' },
];

export function jobDisplayStatus(status: string): JobStatusFilter {
  if (status === 'running' || status === 'cancelling' || status === 'queued') return 'running';
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  return 'created';
}

export interface JobStatusCounts {
  total: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  created: number;
}

/**
 * 四项核心指标只统计真实任务列表：
 * - 运行中：running / cancelling（取消中仍占用资源）
 * - 已取消不计入失败
 * - created / waiting 不计入运行中
 */
export function countJobStatuses(jobs: JobSummary[]): JobStatusCounts {
  const counts: JobStatusCounts = {
    total: jobs.length,
    running: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
    created: 0,
  };

  for (const job of jobs) {
    const group = jobDisplayStatus(job.status);
    if (group === 'running') counts.running += 1;
    else if (group === 'completed') counts.completed += 1;
    else if (group === 'failed') counts.failed += 1;
    else if (group === 'cancelled') counts.cancelled += 1;
    else counts.created += 1;
  }

  return counts;
}

export interface StatusDistributionItem {
  status: Exclude<JobStatusFilter, 'all'>;
  label: string;
  value: number;
  color: string;
}

/** “任务状态分布”横向柱状图的数据，颜色沿用 Minimal UI 原始多色色板。 */
export function statusDistribution(jobs: JobSummary[]): StatusDistributionItem[] {
  const counts = countJobStatuses(jobs);

  return [
    { status: 'running', label: '运行中', value: counts.running, color: '#1877F2' },
    { status: 'completed', label: '已完成', value: counts.completed, color: '#22C55E' },
    { status: 'failed', label: '失败', value: counts.failed, color: '#FF5630' },
    { status: 'cancelled', label: '已取消', value: counts.cancelled, color: '#FFAB00' },
    { status: 'created', label: '已创建', value: counts.created, color: '#00B8D9' },
  ];
}

export function filterJobs(
  jobs: JobSummary[],
  query: string,
  status: JobStatusFilter,
): JobSummary[] {
  const keyword = query.trim().toLowerCase();

  return jobs.filter((job) => {
    if (status !== 'all' && jobDisplayStatus(job.status) !== status) return false;
    if (!keyword) return true;

    return (
      job.job_id.toLowerCase().includes(keyword) ||
      job.dataset.toLowerCase().includes(keyword)
    );
  });
}

function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatMonthDay(date: Date): string {
  return `${`${date.getMonth() + 1}`.padStart(2, '0')}-${`${date.getDate()}`.padStart(2, '0')}`;
}

export interface DailyJobCount {
  labels: string[];
  values: number[];
}

/** 近七个自然日（含今天）的新建任务数，按浏览器本地时区统计。 */
export function jobsLastSevenDays(jobs: JobSummary[], now: Date = new Date()): DailyJobCount {
  const days: Date[] = [];
  const base = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  for (let offset = 6; offset >= 0; offset -= 1) {
    days.push(new Date(base.getFullYear(), base.getMonth(), base.getDate() - offset));
  }

  const buckets = new Map(days.map((day) => [localDayKey(day), 0]));

  for (const job of jobs) {
    const created = new Date(job.created_at);
    if (Number.isNaN(created.getTime())) continue;
    const key = localDayKey(created);
    const current = buckets.get(key);
    if (current !== undefined) buckets.set(key, current + 1);
  }

  return {
    labels: days.map(formatMonthDay),
    values: days.map((day) => buckets.get(localDayKey(day)) ?? 0),
  };
}

// ----------------------------------------------------------------------
// 阶段可见性：优先 requested_stages；旧任务用 not_integrated 回退
// ----------------------------------------------------------------------

export interface StageVisibilitySource {
  requested_stages?: StageKey[];
  // 列表接口给状态字符串，详情接口给阶段对象；两者都按展示状态读取。
  stages: Partial<Record<StageKey, string | { status?: string }>>;
}

function stageStatus(source: string | { status?: string } | undefined): string | undefined {
  if (typeof source === 'string') return source;
  return source?.status;
}

export function visibleStageKeys(job: StageVisibilitySource): StageKey[] {
  if (job.requested_stages && job.requested_stages.length > 0) {
    return STAGE_ORDER.filter((stage) => job.requested_stages?.includes(stage));
  }

  return STAGE_ORDER.filter((stage) => stageStatus(job.stages[stage]) !== 'not_integrated');
}

export function isStageRequested(job: StageVisibilitySource, stage: StageKey): boolean {
  return visibleStageKeys(job).includes(stage);
}
