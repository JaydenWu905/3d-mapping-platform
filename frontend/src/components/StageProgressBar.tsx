import type { StageDetail } from '../types';
import { measuredProgress } from './runInsight';

export function StageProgressBar({ stage, large = false }: { stage: StageDetail; large?: boolean }) {
  const bar = measuredProgress(stage);
  return (
    <div className="stage-progress-visual">
      {bar.percent !== null ? (
        <div className={`progress-bg ${large ? 'progress-lg' : ''}`}
          role="progressbar"
          aria-label={bar.kind === 'input' ? (stage.stage === 'pose' ? '输入发布进度（非位姿阶段进度）' : '输入处理进度（非整个阶段完成）') : bar.kind === 'step' ? '当前环节进度（非整个阶段完成）' : '阶段完成状态'}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={bar.kind === 'stage' || stage.stage === 'pose' ? Math.round(bar.percent) : bar.percent === 100 ? 100 : Math.min(99.9, Math.floor(Number(bar.percent.toFixed(10)) * 10) / 10)}>
          <div className="progress-fill" style={{ width: `${bar.percent}%` }} />
        </div>
      ) : null}
      {stage.status === 'running' && bar.percent === null ? stage.stage === 'pose' ? <span className="progress-activity" role="status" aria-label="正在处理，暂无可计量百分比" /> : <div className={`progress-bg progress-indeterminate ${large ? 'progress-lg' : ''}`} role="progressbar" aria-label="处理中，当前环节总量未知"><span className="progress-indeterminate__fill" /><span className="progress-indeterminate__label">处理中</span></div> : null}
    </div>
  );
}
