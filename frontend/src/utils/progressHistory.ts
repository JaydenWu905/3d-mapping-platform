export type ProgressKind = 'input' | 'stage';

/**
 * 页面观测到的进度样本。只在真实渲染路径上读取 progressBarState，
 * 不根据计时器或缺失字段合成历史。
 */
export interface ProgressSample {
  observedAt: number;
  percent: number;
  kind: ProgressKind;
}

export const MAX_PROGRESS_SAMPLES = 120;
export const PROGRESS_SAMPLE_INTERVAL_MS = 1000;

export interface AppendProgressOptions {
  terminal?: boolean;
  minIntervalMs?: number;
  limit?: number;
}

/**
 * 同一阶段最多每秒记录一个样本；阶段结束时即使不足一秒，
 * 也把最终有效读数补进曲线（相同读数不重复追加）。
 */
export function appendProgressSample(
  samples: ProgressSample[],
  sample: ProgressSample,
  options: AppendProgressOptions = {},
): ProgressSample[] {
  if (!Number.isFinite(sample.percent) || sample.percent < 0 || sample.percent > 100) {
    return samples;
  }

  const minInterval = options.minIntervalMs ?? PROGRESS_SAMPLE_INTERVAL_MS;
  const limit = options.limit ?? MAX_PROGRESS_SAMPLES;
  const last = samples[samples.length - 1];

  if (last) {
    const sameReading = last.percent === sample.percent && last.kind === sample.kind;
    const withinInterval = sample.observedAt - last.observedAt < minInterval;

    // 阶段结束：允许突破 1 秒节流，但相同读数不再制造重复点。
    if (options.terminal && sameReading) return samples;
    if (!options.terminal && withinInterval) return samples;
  }

  const next = [...samples, sample];
  return next.length > limit ? next.slice(next.length - limit) : next;
}
