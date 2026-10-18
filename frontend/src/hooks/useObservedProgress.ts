import { useEffect, useState } from 'react';

import { progressBarState } from '../components/progressLabel';
import type { JobDetail, StageKey } from '../types';
import {
  appendProgressSample,
  type ProgressKind,
  type ProgressSample,
} from '../utils/progressHistory';

const ACTIVE_STATUSES = new Set(['running', 'queued', 'cancelling']);
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

interface HistoryState {
  jobId: string;
  runs: Partial<Record<StageKey, string>>;
  samples: Partial<Record<StageKey, ProgressSample[]>>;
}

/**
 * 观测“本次页面打开后”看到的分阶段进度。
 *
 * - 只读取 progressBarState 的真实百分比，不根据计时器补点；
 * - 同阶段最多每秒一个样本，阶段结束补最终读数；
 * - 任务切换或阶段重跑（started_at 变化）时清空该阶段历史；
 * - 刷新页面后从当前读数重新观测，不合成历史曲线。
 */
export function useObservedProgress(
  job: JobDetail | null,
  stageKey: StageKey | null,
): ProgressSample[] {
  const [history, setHistory] = useState<HistoryState>({
    jobId: '',
    runs: {},
    samples: {},
  });

  const stage = job && stageKey ? job.stages[stageKey] : undefined;
  const runKey =
    job && stageKey && stage ? `${job.job_id}:${stageKey}:${stage.started_at ?? 'pending'}` : '';
  const bar = stage ? progressBarState(stage) : null;
  const percent = bar?.percent ?? null;
  const kind: ProgressKind = bar?.kind ?? 'stage';
  const shouldSample =
    !!stage &&
    percent !== null &&
    (ACTIVE_STATUSES.has(stage.status) || TERMINAL_STATUSES.has(stage.status));
  const terminal = !!stage && TERMINAL_STATUSES.has(stage.status);

  useEffect(() => {
    if (!job || !stageKey || !runKey || !shouldSample || percent === null) return;

    setHistory((previous) => {
      const sameJob = previous.jobId === job.job_id;
      const runs = sameJob ? previous.runs : {};
      const allSamples = sameJob ? previous.samples : {};
      const base = runs[stageKey] === runKey ? (allSamples[stageKey] ?? []) : [];
      const nextSamples = appendProgressSample(
        base,
        { observedAt: Date.now(), percent, kind },
        { terminal },
      );

      if (nextSamples === base) return previous;

      return {
        jobId: job.job_id,
        runs: { ...runs, [stageKey]: runKey },
        samples: { ...allSamples, [stageKey]: nextSamples },
      };
    });
  }, [job, stageKey, runKey, shouldSample, percent, kind, terminal]);

  if (!job || !stageKey || history.jobId !== job.job_id) return [];
  return history.samples[stageKey] ?? [];
}
