import type { StageDetail } from '../types';
import { measuredProgress } from './runInsight';

export function StageProgressBar({ stage, large = false }: { stage: StageDetail; large?: boolean }) {
  const bar = measuredProgress(stage);
  return (
    <div className="stage-progress-visual">
      {bar.percent !== null ? (
        <div className={`progress-bg ${large ? 'progress-lg' : ''}`}
          role="progressbar"
          aria-label={bar.kind === 'input' ? '输入发布进度（非位姿阶段进度）' : '阶段完成状态'}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar.percent)}>
          <div className="progress-fill" style={{ width: `${bar.percent}%` }} />
        </div>
      ) : null}
      {stage.status === 'running' && bar.percent === null ? <span className="progress-activity" role="status" aria-label="正在处理，暂无可计量百分比" /> : null}
    </div>
  );
}
