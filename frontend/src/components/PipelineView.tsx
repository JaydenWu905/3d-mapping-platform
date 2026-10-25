import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { JobDetail, StageKey } from '../types';
import { STAGE_ORDER, STAGE_NAMES, visibleStageKeys } from '../utils/jobDisplay';
import { StageCard } from './StageCard';

// 阶段展示名称只绑定"阶段键"，绝不绑定后端算法名（架构约束）。
export const STAGE_LABELS: Record<string, string> = { ...STAGE_NAMES };

export const BACKEND_STATUS_LABELS: Record<string, string> = {
  ready: '就绪',
  experimental: '实验性',
  disabled: '已禁用',
};

export interface PipelineViewProps {
  job: JobDetail;
  selectedStage: string;
  busy: boolean;
  onSelectStage: (stage: string) => void;
  onStart: (stage: string) => void;
  onCancel: (stage: string) => void;
  onRetry: (stage: string) => void;
}

function unrequestedMessage(stage: StageKey): string {
  return stage === 'distance'
    ? '本任务未请求距离场'
    : `本任务未请求${STAGE_NAMES[stage] ?? stage}`;
}

function UnrequestedStage({ stage }: { stage: StageKey }) {
  const message = unrequestedMessage(stage);

  return (
    <Box
      sx={{
        p: 1.5,
        minWidth: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        bgcolor: 'background.neutral',
        border: '1px dashed',
        borderColor: 'divider',
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <Box
          component="span"
          sx={{
            flex: 'none',
            width: 24,
            height: 24,
            display: 'grid',
            placeItems: 'center',
            fontSize: 'var(--font-secondary)',
            fontWeight: 700,
            color: 'text.disabled',
            bgcolor: 'grey.200',
          }}
        >
          {stage === 'pose' ? '①' : stage === 'surface' ? '②' : '③'}
        </Box>
        <Typography sx={{ fontSize: 18, fontWeight: 700, color: 'text.secondary' }}>
          {STAGE_NAMES[stage] ?? stage}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Typography
          sx={{
            flex: 'none',
            px: 1,
            py: 0.25,
            fontSize: 'var(--font-secondary)',
            fontWeight: 600,
            color: 'text.disabled',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          未请求
        </Typography>
      </Stack>

      <Typography sx={{ fontSize: 'var(--font-body)', color: 'text.secondary', mt: 1 }}>{message}</Typography>
      <Typography sx={{ fontSize: 'var(--font-secondary)', color: 'text.disabled', mt: 'auto' }}>
        本阶段未纳入本次任务范围，不影响其他阶段结果。
      </Typography>
    </Box>
  );
}

export function PipelineView({
  job,
  selectedStage,
  busy,
  onSelectStage,
  onStart,
  onCancel,
  onRetry,
}: PipelineViewProps) {
  const visible = new Set(visibleStageKeys(job));

  return (
    <Box>
      <Typography
        sx={{
          mb: 1,
          fontSize: 'var(--font-body)',
          fontWeight: 600,
          color: 'text.secondary',
          letterSpacing: '0.04em',
        }}
      >
        处理管线
      </Typography>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: 'minmax(0, 1fr)',
            md: `repeat(${STAGE_ORDER.length}, minmax(0, 1fr))`,
          },
          gap: 1.5,
        }}
      >
        {STAGE_ORDER.map((stage) => {
          const detail = job.stages[stage];
          if (detail && visible.has(stage)) {
            return (
              <StageCard
                key={stage}
                stageKey={stage}
                label={STAGE_LABELS[stage] ?? stage}
                detail={detail}
                selected={stage === selectedStage}
                busy={busy}
                onSelect={() => onSelectStage(stage)}
                onStart={() => onStart(stage)}
                onCancel={() => onCancel(stage)}
                onRetry={() => onRetry(stage)}
              />
            );
          }

          return <UnrequestedStage key={stage} stage={stage} />;
        })}
      </Box>
    </Box>
  );
}
