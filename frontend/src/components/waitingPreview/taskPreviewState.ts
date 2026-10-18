import type { JobDetail, StageKey } from '../../types';
import { visibleStageKeys } from '../../utils/jobDisplay';
import { hasUsablePreview } from './artifacts';

export type PreviewChoice = {
  jobId: string;
  mode: 'animation' | 'results';
  resultStageKey: StageKey | null;
  /** 仅用户明确点选未运行/异常阶段时展示该阶段说明，默认跟随当前执行阶段。 */
  animationStageKey: StageKey | null;
};

export function initialPreviewChoice(jobId: string): PreviewChoice {
  return { jobId, mode: 'animation', resultStageKey: null, animationStageKey: null };
}

export function deriveTaskPreview(job: JobDetail | null, choice: PreviewChoice) {
  const keys = job ? visibleStageKeys(job) : [];
  const availableResults = job ? keys.filter(key => hasUsablePreview(job.stages[key])) : [];
  const activeStageKey = job
    ? keys.find(key => ['running', 'cancelling'].includes(job.stages[key].status))
      ?? keys.find(key => job.stages[key].status === 'queued') ?? null
    : null;
  const current = choice.jobId === job?.job_id ? choice : initialPreviewChoice(job?.job_id ?? '');
  const latestResult = availableResults[availableResults.length - 1] ?? null;
  const resultStageKey = current.mode === 'results' && current.resultStageKey && availableResults.includes(current.resultStageKey)
    ? current.resultStageKey : latestResult;
  const terminal = !!job && ['completed', 'failed', 'cancelled'].includes(job.status);
  const mode = resultStageKey && (current.mode === 'results' || (terminal && !activeStageKey && !current.animationStageKey))
    ? 'results' as const : 'animation' as const;
  const override = current.animationStageKey && keys.includes(current.animationStageKey) ? current.animationStageKey : null;
  const fallback = job ? keys.find(key => ['failed', 'cancelled'].includes(job.stages[key].status))
    ?? keys.find(key => job.stages[key].status === 'waiting')
    ?? keys[keys.length - 1] ?? null : null;
  return {
    activeStageKey,
    availableResults,
    resultStageKey,
    mode,
    viewStageKey: mode === 'results' ? resultStageKey : override ?? activeStageKey ?? fallback,
  };
}

export function choosePreviewStage(job: JobDetail, key: StageKey): PreviewChoice {
  if (hasUsablePreview(job.stages[key])) {
    return { jobId: job.job_id, mode: 'results', resultStageKey: key, animationStageKey: null };
  }
  return {
    jobId: job.job_id, mode: 'animation', resultStageKey: null,
    animationStageKey: ['running', 'queued', 'cancelling'].includes(job.stages[key].status) ? null : key,
  };
}
