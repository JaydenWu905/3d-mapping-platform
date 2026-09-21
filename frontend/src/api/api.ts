import type { BackendsResponse, DatasetInfo, JobDetail, JobSummary } from '../types';

const BASE = '/api';

interface ErrorBody {
  detail?: unknown;
}

export function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as ErrorBody;
      if (body.detail !== undefined) {
        msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* 非 JSON 错误体，保留默认信息 */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// 归档 / 预览地址一律只由 artifact_id 拼出，绝不接收客户端路径。
const jobUrl = (jobId: string) => `/jobs/${encodeURIComponent(jobId)}`;
const stageUrl = (jobId: string, stage: string) => `${jobUrl(jobId)}/stages/${encodeURIComponent(stage)}`;

export const api = {
  eventsUrl: (jobId: string) => `${BASE}${jobUrl(jobId)}/events`,

  // 预览（role === 'preview'，缩略图/前端渲染用）
  previewUrl: (jobId: string, stage: string, artifactId: string) =>
    `${BASE}${stageUrl(jobId, stage)}/previews/${encodeURIComponent(artifactId)}`,

  // 下载（后端要求 manifest 中 download === true，否则 404）
  artifactUrl: (jobId: string, stage: string, artifactId: string) =>
    `${BASE}${stageUrl(jobId, stage)}/artifacts/${encodeURIComponent(artifactId)}`,

  listJobs: () => request<JobSummary[]>('/jobs'),
  getJob: (jobId: string) => request<JobDetail>(jobUrl(jobId)),
  createJob: (body: { dataset: string; backends: Record<string, string>; fail_stage?: string | null }) =>
    request<JobDetail>('/jobs', { method: 'POST', body: JSON.stringify(body) }),
  deleteJob: (jobId: string) => request<void>(jobUrl(jobId), { method: 'DELETE' }),

  runAll: (jobId: string) =>
    request<{ status: string }>(`${jobUrl(jobId)}/run-all`, { method: 'POST' }),
  startStage: (jobId: string, stage: string) =>
    request<{ status: string }>(`${stageUrl(jobId, stage)}/start`, { method: 'POST' }),
  cancelStage: (jobId: string, stage: string) =>
    request<{ status: string }>(`${stageUrl(jobId, stage)}/cancel`, { method: 'POST' }),
  retryStage: (jobId: string, stage: string) =>
    request<{ status: string }>(`${stageUrl(jobId, stage)}/retry`, { method: 'POST' }),

  getLogs: (jobId: string, stage: string, offset = 0, limit = 400) =>
    request<{ offset: number; total: number; lines: string[] }>(
      `${stageUrl(jobId, stage)}/logs?offset=${offset}&limit=${limit}`,
    ),

  // 任意 preview 文件（JSON）读取，前端自带时填充图/轨迹用。
  getPreviewJson: async (jobId: string, stage: string, artifactId: string): Promise<unknown> => {
    const res = await fetch(api.previewUrl(jobId, stage, artifactId));
    if (!res.ok) throw new Error(`preview ${res.status}`);
    return (await res.json()) as unknown;
  },

  getBackends: () => request<BackendsResponse>('/backends'),
  getDatasets: () => request<DatasetInfo[]>('/datasets'),
};