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
import { stageProgressPatch } from '../components/stageProgressPatch';

export interface JobActions {
  runAll: () => Promise<void>;
  runPlanned: () => Promise<void>;
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
 * - 连接断开时保留最后一次数据；由下方的重连循环负责恢复，重连成功后 REST 补齐缺失事件。
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
    let closed = false;
    let es: EventSource | null = null;
    let retryTimer: number | undefined;
    let retryDelay = 2000;
    let hasOpened = false;
    const terminal = (status: string | undefined) =>
      status === 'completed' || status === 'failed' || status === 'cancelled';

    const scheduleReconnect = () => {
      if (closed || retryTimer !== undefined) return;
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined;
        connect();
      }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 10000);
    };

    const connect = () => {
      if (closed) return;
      const stream = new EventSource(api.eventsUrl(jobId));
      es = stream;

      stream.addEventListener('open', () => {
        if (closed) return;
        retryDelay = 2000;
        setConnected(true);
        // 断线期间的事件可能已错过，重连后先 REST 全量补齐。
        if (hasOpened) void refresh();
        hasOpened = true;
      });
      stream.addEventListener('error', () => {
        if (closed) return;
        setConnected(false);
        // 后端不可用时代理会返回 5xx，EventSource 遇到非 2xx 会永久失败，
        // 不再自动重连；因此由这里接管重连并做退避。
        stream.close();
        if (es === stream) es = null;
        scheduleReconnect();
      });

      stream.addEventListener('snapshot', (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as SnapshotEvent;
          setJob(data);
        } catch {
          /* 忽略坏帧 */
        }
      });

      stream.addEventListener('job.status', (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as JobStatusEvent;
          setJob((prev) => (prev ? { ...prev, status: data.status } : prev));
          if (terminal(data.status)) void refresh();
        } catch {
          /* ignore */
        }
      });

      stream.addEventListener('stage.status', (ev: MessageEvent) => {
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

      stream.addEventListener('stage.progress', (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as StageProgressEvent;
          setJob((prev) => {
            return patchStage(prev, data.stage, stageProgressPatch(data));
          });
        } catch {
          /* ignore */
        }
      });

      // 阶段产生结果/manifest 时，REST 拉一次全量（manifest、进度文件落盘完成）。
      stream.addEventListener('stage.result', (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as StageResultEvent;
          // Terminal truth lives on disk (progress + manifest). Re-fetching also
          // repairs any coalesced/dropped live progress frame.
          if (data && data.stage) void refresh();
        } catch {
          /* ignore */
        }
      });
    };

    connect();

    return () => {
      closed = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      es?.close();
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
    runPlanned: () => call(() => api.runPlanned(jobIdRef.current!)),
    startStage: (stage) => call(() => api.startStage(jobIdRef.current!, stage)),
    cancelStage: (stage) => call(() => api.cancelStage(jobIdRef.current!, stage)),
    retryStage: (stage) => call(() => api.retryStage(jobIdRef.current!, stage)),
    deleteJob: () => call(() => api.deleteJob(jobIdRef.current!)),
  };

  return { job, error, connected, refresh, actions };
}
