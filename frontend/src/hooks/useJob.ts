import { useCallback, useEffect, useRef, useState } from 'react';
import { api, messageOf } from '../api/api';
import { isStageKey } from '../types';
import type {
  JobDetail,
  JobStatusEvent,
  SnapshotEvent,
  StageDetail,
  StageProgressEvent,
  StageResultEvent,
  StageStatusEvent,
} from '../types';

export interface JobActions {
  runAll: () => Promise<void>;
  startStage: (stage: string) => Promise<void>;
  cancelStage: (stage: string) => Promise<void>;
  retryStage: (stage: string) => Promise<void>;
  deleteJob: () => Promise<void>;
}

export interface JobState {
  job: JobDetail | null;
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
  actions: JobActions;
}

function patchStage(prev: JobDetail | null, stage: string, patch: Partial<StageDetail>): JobDetail | null {
  if (!prev || !isStageKey(stage) || !prev.stages[stage]) return prev;
  return {
    ...prev,
    stages: { ...prev.stages, [stage]: { ...prev.stages[stage], ...patch } },
  };
}

/**
 * 单个 Job 的 REST + SSE 实时状态。
 * - 挂载时先 REST 拉全量（刷新浏览器后状态从磁盘恢复）。
 * - 之后通过 EventSource 接收 snapshot / stage.progress / stage.status / job.status / stage.result 增量。
 * - 连接断开自动由浏览器重连，重连后收到新 snapshot 全量覆盖。
 */
export function useJob(jobId: string | undefined): JobState {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const jobIdRef = useRef(jobId);
  jobIdRef.current = jobId;

  const refresh = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    try {
      setError(null);
      setJob(await api.getJob(id));
    } catch (e) {
      setError(messageOf(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!jobId) return undefined;
    const es = new EventSource(api.eventsUrl(jobId));
    let closed = false;
    const terminal = (status: string | undefined) =>
      status === 'completed' || status === 'failed' || status === 'cancelled';

    es.addEventListener('open', () => {
      if (!closed) setConnected(true);
    });
    es.addEventListener('error', () => {
      // onerror 也会出现在正常断连后；由浏览器自动重连，重连成功会收到新 snapshot。
      setConnected(false);
    });

    es.addEventListener('snapshot', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as SnapshotEvent;
        setJob(data);
      } catch {
        /* 忽略坏帧 */
      }
    });

    es.addEventListener('job.status', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as JobStatusEvent;
        setJob((prev) => (prev ? { ...prev, status: data.status } : prev));
        if (terminal(data.status)) void refresh();
      } catch {
        /* ignore */
      }
    });

    es.addEventListener('stage.status', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as StageStatusEvent;
        setJob((prev) => {
          const prevStatus = prev && isStageKey(data.stage) ? prev.stages[data.stage]?.status : undefined;
          return patchStage(prev, data.stage, {
            status: (data.status as StageDetail['status'] | undefined) ?? prevStatus,
            message: data.message,
          });
        });
        if (terminal(data.status)) void refresh();
      } catch {
        /* ignore */
      }
    });

    es.addEventListener('stage.progress', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as StageProgressEvent;
        setJob((prev) => {
          const patch: Partial<StageDetail> = {};
          if (data.status) patch.status = data.status as StageDetail['status'];
          if (data.phase !== undefined) patch.phase = data.phase;
          if (data.progress !== undefined) patch.progress = data.progress;
          if (data.current !== undefined) patch.current = data.current;
          if (data.total !== undefined) patch.total = data.total;
          if (data.unit !== undefined) patch.unit = data.unit;
          if (data.message !== undefined) patch.message = data.message;
          if (data.elapsed_sec !== undefined) patch.elapsed_sec = data.elapsed_sec;
          return patchStage(prev, data.stage, patch);
        });
      } catch {
        /* ignore */
      }
    });

    // 阶段产生结果/manifest 时，REST 拉一次全量（manifest、进度文件落盘完成）。
    es.addEventListener('stage.result', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as StageResultEvent;
        // Terminal truth lives on disk (progress + manifest). Re-fetching also
        // repairs any coalesced/dropped live progress frame.
        if (data && data.stage) void refresh();
      } catch {
        /* ignore */
      }
    });

    return () => {
      closed = true;
      es.close();
      setConnected(false);
    };
  }, [jobId, refresh]);

  const call = useCallback(
    async (fn: () => Promise<unknown>) => {
      const id = jobIdRef.current;
      if (!id) return;
      try {
        setError(null);
        await fn();
        await refresh();
      } catch (e) {
        setError(messageOf(e));
      }
    },
    [refresh],
  );

  const actions: JobActions = {
    runAll: () => call(() => api.runAll(jobIdRef.current!)),
    startStage: (stage) => call(() => api.startStage(jobIdRef.current!, stage)),
    cancelStage: (stage) => call(() => api.cancelStage(jobIdRef.current!, stage)),
    retryStage: (stage) => call(() => api.retryStage(jobIdRef.current!, stage)),
    deleteJob: () => call(() => api.deleteJob(jobIdRef.current!)),
  };

  return { job, error, connected, refresh, actions };
}
