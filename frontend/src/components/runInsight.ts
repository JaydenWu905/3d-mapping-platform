import { stagePhaseLabel } from './progressLabel';
import type { JobDetail, StageDetail, StageKey } from '../types';

export type MeasuredProgress = { percent: number | null; label: string; kind: 'input' | 'step' | 'stage' | 'none' };

/** Versioned direct counters describe input or a named step, never an overall
 * runtime estimate. Legacy log/milestone records remain non-percentage displays. */
export function measuredProgress(stage: StageDetail): MeasuredProgress {
  if (stage.status === 'completed') return { percent: 100, label: '阶段已完成', kind: 'stage' };
  const counts = stage.stage === 'surface' && typeof stage.selected_frames === 'number'
    ? `已选中 ${stage.selected_frames.toLocaleString('zh-CN')} · 已关联 ${(stage.matched_frames ?? 0).toLocaleString('zh-CN')} · 已融合 ${(stage.fused_frames ?? 0).toLocaleString('zh-CN')} · 已跳过 ${(stage.skipped_frames ?? 0).toLocaleString('zh-CN')} 帧` : '';
  if (stage.status !== 'running') return { percent: null, label: ['failed','cancelled','cancelling'].includes(stage.status) ? counts : '', kind: 'none' };
  const quiet = (stage.counter_age_sec ?? 0) >= 15 ? ' · 暂无新计数，仍在处理中' : '';
  if (stage.progress_run_id && stage.stage === 'surface') {
    const total = stage.selected_frames ?? 0, fused = stage.fused_frames ?? 0;
    if (stage.phase === 'mapping' && total > 0 && fused >= 0 && fused <= total) {
      const percent = fused / total * 100;
      return {percent,kind:'input',label:`输入处理进度 ${Math.floor(fused * 1000 / total) / 10}%（非整个阶段完成） · ${counts}${quiet}`};
    }
    return {percent:null,kind:'none',label:`${stagePhaseLabel(stage)} · 处理中${counts ? ` · ${counts}` : ''}${quiet}`};
  }
  if (stage.progress_run_id && stage.stage === 'distance') {
    const current = stage.current ?? 0, total = stage.total ?? 0;
    const phase = stagePhaseLabel(stage);
    if (stage.progress_scope === 'step' && Number.isFinite(total) && total > 0 && Number.isFinite(current) && current >= 0 && current <= total) {
      const percent = current / total * 100;
      return {percent,kind:'step',label:`${phase} ${Math.floor(current * 1000 / total) / 10}% · ${current.toLocaleString('zh-CN')}/${total.toLocaleString('zh-CN')} ${stage.unit}（仅当前环节，阶段仍在运行）${quiet}`};
    }
    return {percent:null,kind:'none',label:`${phase} · 处理中${current > 0 ? ` · 已处理 ${current.toLocaleString('zh-CN')} ${stage.unit}` : '（当前环节无可计量总量）'}${quiet}`};
  }
  if (stage.stage === 'pose' && stage.backend === 'glim') {
    const total = Number(stage.lidar_total ?? 0);
    const current = Number(stage.lidar_published ?? 0);
    if (total > 0 && Number.isFinite(current) && current >= 0 &&
        ['input_publishing', 'waiting_glim_export', 'associating'].includes(stage.phase)) {
      const percent = Math.max(0, Math.min(100, current / total * 100));
      return { percent, label: `输入发布 ${Math.round(percent)}% · LiDAR ${current}/${total} 帧；位姿阶段仍在运行`, kind: 'input' };
    }
    return { percent: null, label: '等待首个输入计数', kind: 'none' };
  }
  if (stage.stage === 'surface') {
    const calls = Number(stage.current);
    if (stage.phase === 'mapping' && calls > 0 && Number.isFinite(calls)) {
      return { percent: null, label: `已完成 ${calls.toLocaleString('zh-CN')} 次融合调用（非已融合帧数）`, kind: 'none' };
    }
    return { percent: null, label: '正在准备 / 等待首个进度', kind: 'none' };
  }
  return { percent: null, label: '当前环节按状态展示', kind: 'none' };
}

export type DurationRow = { key: StageKey; seconds: number | null; status: string };
export function durationRows(job: JobDetail, keys: StageKey[], liveElapsed: Partial<Record<StageKey, number>> = {}): DurationRow[] {
  return keys.map(key => {
    const stage = job.stages[key];
    const active = stage.status === 'running' || stage.status === 'cancelling';
    const raw = active ? liveElapsed[key] ?? stage.elapsed_sec :
      stage.status === 'completed' || stage.status === 'failed' || stage.status === 'cancelled'
        ? stage.elapsed_sec || stage.manifest?.runtime_sec : null;
    return { key, status: stage.status, seconds: typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? raw : active ? .1 : null };
  });
}

export type CountSample = { at: number; count: number };
/** Stable input-rate estimate covers input publishing only, never GLIM export. */
export function inputEta(stage: StageDetail, samples: CountSample[]): number | null {
  const total = Number(stage.lidar_total ?? 0);
  const current = Number(stage.lidar_published ?? 0);
  if (stage.stage !== 'pose' || stage.backend !== 'glim' || stage.status !== 'running' ||
      stage.phase !== 'input_publishing' || total < 50 || current >= total || current < 0 || samples.length < 3) return null;
  const valid = samples.filter(s => Number.isFinite(s.at) && Number.isFinite(s.count));
  const first = valid[0], last = valid[valid.length - 1];
  if (!first || !last || last.at - first.at < 30000 || last.count - first.count < Math.max(20, total * .05)) return null;
  const middle = valid[Math.floor(valid.length / 2)];
  const left = (middle.count - first.count) / ((middle.at - first.at) / 1000);
  const right = (last.count - middle.count) / ((last.at - middle.at) / 1000);
  if (!Number.isFinite(left) || !Number.isFinite(right) || left <= 0 || right <= 0 ||
      Math.max(left, right) / Math.min(left, right) > 1.5) return null;
  const seconds = (total - current) / ((last.count - first.count) / ((last.at - first.at) / 1000));
  return Number.isFinite(seconds) && seconds >= 5 && seconds <= 7200 ? seconds : null;
}

function sameScope(a: JobDetail, b: JobDetail): boolean {
  return a.dataset === b.dataset && a.run_mode === b.run_mode &&
    JSON.stringify(a.run_scope ?? null) === JSON.stringify(b.run_scope ?? null) &&
    !!a.device_config?.sha256 && a.device_config.sha256 === b.device_config?.sha256 &&
    !a.preview_job && !b.preview_job;
}

/** Keep only exact dataset, mode, scope, device and backend matches. */
export function historicalStageSeconds(job: JobDetail, candidates: JobDetail[], key: StageKey): number | null {
  const values = candidates.filter(other => other.job_id !== job.job_id && sameScope(job, other) &&
    job.backends[key] === other.backends[key] && other.stages[key]?.status === 'completed')
    .map(other => other.stages[key].elapsed_sec || other.stages[key].manifest?.runtime_sec || 0)
    .filter(value => Number.isFinite(value) && value >= 15).sort((a, b) => a - b);
  return values.length ? values[Math.floor(values.length / 2)] : null;
}

export function stageEta(stage: StageDetail, elapsed: number, historySeconds: number | null, inputSeconds: number | null): string {
  if (stage.status !== 'running') return '剩余时间暂无法估算';
  if (inputSeconds !== null) return `本次输入发布速率估计，约 ${roundedEstimate(inputSeconds)}（仅输入发布）`;
  // Once an old run's remaining time becomes too short, stop counting down.
  if (historySeconds !== null && elapsed >= 0 && elapsed < historySeconds * .8) {
    return `参考历史运行，约 ${roundedEstimate(historySeconds - elapsed)}`;
  }
  return '剩余时间暂无法估算';
}

function roundedEstimate(seconds: number): string {
  const rounded = Math.max(10, Math.ceil(seconds / 10) * 10);
  if (rounded < 60) return `${rounded} 秒`;
  return `${Math.ceil(rounded / 60)} 分钟`;
}
