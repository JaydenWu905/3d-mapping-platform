import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { StageDetail } from '../types';
import { BACKEND_STATUS_LABELS } from './PipelineView';
import {
  blockedReasonLabel,
  formatElapsed,
  progressLabel,
  stageMessageLabel,
  stageProgressText,
} from './progressLabel';
import { StageProgressBar } from './StageProgressBar';
import { StatusBadge } from './StatusBadge';

export interface StageCardProps {
  stageKey: string;
  label: string;
  detail: StageDetail;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onStart: () => void;
  onCancel: () => void;
  onRetry: () => void;
}

/** 阶段顺序号只绑定阶段键，不绑定后端算法名。 */
const STAGE_INDEX: Record<string, string> = {
  pose: '①',
  surface: '②',
  distance: '③',
};

export function StageCard({
  stageKey,
  label,
  detail,
  selected,
  busy,
  onSelect,
  onStart,
  onCancel,
  onRetry,
}: StageCardProps) {
  const running =
    detail.status === 'running' || detail.status === 'cancelling' || detail.status === 'queued';

  return (
    <Box
      onClick={onSelect}
      aria-current={selected ? 'step' : undefined}
      sx={{
        p: 1.5,
        minWidth: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        cursor: 'pointer',
        bgcolor: selected ? 'primary.lighter' : 'background.paper',
        border: '1px solid',
        borderColor: selected ? 'primary.main' : 'divider',
        transition: (theme) =>
          theme.transitions.create(['border-color', 'background-color'], {
            duration: theme.transitions.duration.shorter,
          }),
        '&:hover': { borderColor: selected ? 'primary.main' : 'grey.400' },
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
        <Box
          component="span"
          sx={{
            flex: 'none',
            width: 24,
            height: 24,
            display: 'grid',
            placeItems: 'center',
            fontSize: 13,
            fontWeight: 700,
            color: running || selected ? 'common.white' : 'text.secondary',
            bgcolor: running ? 'primary.main' : selected ? 'primary.dark' : 'grey.200',
          }}
        >
          {STAGE_INDEX[stageKey] ?? '·'}
        </Box>
        <Typography sx={{ fontSize: 18, fontWeight: 700, whiteSpace: 'nowrap' }}>
          {label}
        </Typography>
        <Box sx={{ flex: 1, minWidth: 8 }} />
        <StatusBadge status={detail.status} />
      </Stack>

      <Typography
        title={`backend: ${detail.backend}`}
        sx={{
          fontSize: 13,
          color: 'text.secondary',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        算法：
        <Box component="span" sx={{ color: 'text.primary', fontWeight: 600 }}>
          {detail.backend_display || detail.backend || '未选择'}
        </Box>
        {' · '}状态 {BACKEND_STATUS_LABELS[detail.backend_status] ?? detail.backend_status}
      </Typography>

      <Box title={detail.phase || detail.message || ''} sx={{ minWidth: 0 }}>
        <StageProgressBar stage={detail} />
        <Stack direction="row" spacing={1} justifyContent="space-between" sx={{ mt: 0.5 }}>
          <Typography
            title={progressLabel(detail)}
            sx={{
              fontSize: 12,
              color: 'text.secondary',
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {progressLabel(detail)}
          </Typography>
          <Typography sx={{ flex: 'none', fontSize: 12, color: 'text.secondary' }}>
            {stageProgressText(detail)}
          </Typography>
        </Stack>
      </Box>

      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 'auto', minWidth: 0 }}>
        <Typography
          title={detail.message}
          sx={{
            flex: 1,
            minWidth: 0,
            fontSize: 12,
            color: 'text.secondary',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {stageMessageLabel(detail)}
        </Typography>
        <Typography sx={{ flex: 'none', fontSize: 12, color: 'text.disabled' }}>
          {formatElapsed(detail.elapsed_sec)}
        </Typography>
        <Box
          onClick={(event) => event.stopPropagation()}
          sx={{ flex: 'none', display: 'flex', alignItems: 'center' }}
        >
          <StageButton
            detail={detail}
            busy={busy}
            onStart={onStart}
            onCancel={onCancel}
            onRetry={onRetry}
          />
        </Box>
      </Stack>
    </Box>
  );
}

function StageButton({
  detail,
  busy,
  onStart,
  onCancel,
  onRetry,
}: {
  detail: StageDetail;
  busy: boolean;
  onStart: () => void;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const { status, can_run, run_blocked_reason } = detail;

  if (status === 'running' || status === 'cancelling' || status === 'queued') {
    return (
      <Button
        variant="outlined"
        color="error"
        size="small"
        onClick={onCancel}
        disabled={busy}
        sx={{ whiteSpace: 'nowrap' }}
      >
        {status === 'cancelling' ? '取消中…' : '取消'}
      </Button>
    );
  }

  if (status === 'completed' || status === 'failed' || status === 'cancelled') {
    return (
      <Button
        variant="text"
        size="small"
        onClick={onRetry}
        disabled={busy}
        sx={{ whiteSpace: 'nowrap' }}
      >
        ↻ 重跑
      </Button>
    );
  }

  if (!can_run) {
    return (
      <Typography
        title={run_blocked_reason}
        sx={{
          maxWidth: 130,
          fontSize: 12,
          color: 'text.disabled',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        不可启动 · {blockedReasonLabel(run_blocked_reason)}
      </Typography>
    );
  }

  return (
    <Button
      variant="contained"
      size="small"
      onClick={onStart}
      disabled={busy}
      sx={{ whiteSpace: 'nowrap' }}
    >
      ▶ 启动
    </Button>
  );
}
