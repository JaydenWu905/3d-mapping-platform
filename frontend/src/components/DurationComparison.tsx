import type { StageKey } from '../types';
import { STAGE_NAMES } from '../utils/jobDisplay';
import { formatElapsed } from './progressLabel';
import type { DurationRow } from './runInsight';

const STATE: Record<string, string> = {
  running: '运行中', cancelling: '取消中', completed: '已完成',
  failed: '失败', cancelled: '已取消', queued: '等待计算资源',
};

export function DurationComparison({ rows }: { rows: DurationRow[] }) {
  const maximum = Math.max(0, ...rows.map(row => row.seconds ?? 0));
  // Fixed row geometry; the longest currently measured stage sets the scale.
  const scale = maximum;
  return <section className="duration-comparison" aria-label="各阶段耗时比较">
    <h3>各阶段耗时比较</h3>
    {scale === 0 ? <p className="duration-comparison__empty">阶段尚未开始，暂无耗时数据。</p> : null}
    {rows.map(row => <div className="duration-comparison__row" data-duration-stage={row.key} key={row.key}>
      <span className="duration-comparison__name">{STAGE_NAMES[row.key as StageKey]}</span>
      <div className="duration-comparison__track" aria-hidden="true">
        {row.seconds !== null && scale > 0 ? <span className={`duration-comparison__bar duration-comparison__bar--${row.key}`}
          style={{ width: `${Math.max(2, row.seconds / scale * 100)}%` }} /> : null}
      </div>
      <span className="duration-comparison__value">{row.seconds !== null ? formatElapsed(row.seconds) :
        row.status === 'waiting' || row.status === 'queued' ? '尚未开始' : '未记录耗时'}
        {STATE[row.status] && row.seconds !== null ? <small> · {STATE[row.status]}</small> :
          row.status === 'queued' ? <small> · 等待计算资源</small> : null}
      </span>
    </div>)}
  </section>;
}
