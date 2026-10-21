import Chip from '@mui/material/Chip';

import type { StageStatus } from '../types';

export const STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  waiting: '等待中',
  queued: '排队中',
  not_integrated: '未请求',
  running: '运行中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

type StatusTone = 'default' | 'primary' | 'info' | 'success' | 'warning' | 'error';

/** 状态语义色：运行中使用主色蓝，成功/失败/取消沿用 Minimal UI 多色体系。 */
const STATUS_TONES: Record<string, StatusTone> = {
  created: 'default',
  waiting: 'default',
  queued: 'info',
  not_integrated: 'default',
  running: 'primary',
  cancelling: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'warning',
};

export function StatusBadge({
  status,
  size = 'small',
}: {
  status: string;
  size?: 'small' | 'medium';
}) {
  const tone = STATUS_TONES[status] ?? 'default';
  const medium = size === 'medium';

  return (
    <Chip
      label={STATUS_LABELS[status] ?? status}
      size={size}
      sx={{
        borderRadius: 0,
        height: medium ? 30 : 26,
        fontSize: medium ? 'var(--font-body)' : 'var(--font-secondary)',
        fontWeight: 600,
        color: tone === 'default' ? 'text.secondary' : `${tone}.dark`,
        bgcolor: tone === 'default' ? 'grey.100' : `${tone}.lighter`,
        border: '1px solid',
        borderColor: tone === 'default' ? 'divider' : `${tone}.main`,
        '& .MuiChip-label': { px: medium ? 1.25 : 1 },
      }}
    />
  );
}

export function stageStatusOf(summaryStatus: string | undefined): StageStatus {
  if (!summaryStatus) return 'waiting';
  return summaryStatus as StageStatus;
}
