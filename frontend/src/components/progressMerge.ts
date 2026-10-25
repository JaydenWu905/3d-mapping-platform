import type { JobDetail, StageDetail } from '../types';

const terminal = (status: string) => ['completed','failed','cancelled'].includes(status);

/** Run identity + source sequence outrank response arrival order and wall clocks. */
export function mergeStageProgress(previous: StageDetail, incoming: Partial<StageDetail>, preferLive = false): StageDetail {
  const oldRun = previous.progress_run_id, newRun = incoming.progress_run_id;
  if (oldRun) {
    if (!newRun) return previous;
    if (oldRun === newRun) {
      if ((incoming.progress_seq ?? -1) < (previous.progress_seq ?? 0)) return previous;
      if (terminal(previous.status) && incoming.status && !terminal(incoming.status)) return previous;
      if (previous.status === 'cancelling' && incoming.status && ['waiting','queued','running'].includes(incoming.status)) return previous;
    } else if (!incoming.progress_started_at || incoming.progress_started_at <= (previous.progress_started_at ?? '')) return previous;
  } else if (preferLive && !newRun && !terminal(incoming.status ?? '')) return previous;
  const merged = {...previous,...incoming};
  if (oldRun && oldRun === newRun && incoming.progress_seq === previous.progress_seq) {
    merged.elapsed_sec = Math.max(previous.elapsed_sec || 0, incoming.elapsed_sec || 0);
    if (previous.counter_updated_at === incoming.counter_updated_at) merged.counter_age_sec = Math.max(previous.counter_age_sec || 0, incoming.counter_age_sec || 0);
  }
  return merged;
}

export function mergeJobSnapshot(previous: JobDetail | null, incoming: JobDetail, preferLive = false): JobDetail | null {
  if (!incoming.stages) return previous;
  if (!previous || previous.job_id !== incoming.job_id) return incoming;
  const stages = {...incoming.stages};
  let retained = false;
  for (const key of ['pose','surface','distance'] as const) {
    if (!previous.stages[key] || !incoming.stages[key]) continue;
    stages[key] = mergeStageProgress(previous.stages[key], incoming.stages[key], preferLive);
    retained ||= stages[key] === previous.stages[key];
  }
  if (!retained) return {...incoming,stages};
  const statuses = (incoming.requested_stages ?? ['pose','surface','distance'] as const).map(key => stages[key].status);
  const status = statuses.some(s=>['running','queued','cancelling'].includes(s)) ? 'running'
    : statuses.includes('failed') ? 'failed' : statuses.includes('cancelled') ? 'cancelled'
    : statuses.every(s=>s==='completed') ? 'completed' : 'created';
  return {...incoming,stages,status};
}
