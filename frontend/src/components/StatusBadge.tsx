import type { StageStatus } from '../types';

export const STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  waiting: '等待中',
  running: '运行中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function stageStatusOf(summaryStatus: string | undefined): StageStatus {
  if (!summaryStatus) return 'waiting';
  return summaryStatus as StageStatus;
}