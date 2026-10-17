import type { StageDetail } from '../types';
import { progressBarState } from './progressLabel';

export function StageProgressBar({ stage, large = false }: { stage: StageDetail; large?: boolean }) {
  const bar = progressBarState(stage);
  return (
    <div className="stage-progress-visual">
      {bar.percent !== null ? (
        <div className={`progress-bg ${large ? 'progress-lg' : ''}`}
          role="progressbar"
          aria-label={bar.kind === 'input' ? '输入发布进度' : '阶段进度'}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar.percent)}>
          <div className="progress-fill" style={{ width: `${bar.percent}%` }} />
        </div>
      ) : null}
      {bar.busy ? <span className="progress-activity" role="status" aria-label="正在处理" /> : null}
    </div>
  );
}
