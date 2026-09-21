import { Fragment, type ReactNode } from 'react';
import type { JobDetail, StageKey } from '../types';
import { StageCard } from './StageCard';

// 阶段展示名称只绑定"阶段键"，绝不绑定后端算法名（架构约束）。
export const STAGE_LABELS: Record<string, string> = {
  pose: 'Pose / SLAM',
  surface: 'Surface Mapping',
  distance: 'Distance / ESDF',
};

export const BACKEND_STATUS_LABELS: Record<string, string> = {
  ready: '就绪',
  experimental: '实验性',
  disabled: '已禁用',
};

const STAGE_DEFAULT_ORDER: StageKey[] = ['pose', 'surface', 'distance'];

export interface PipelineViewProps {
  job: JobDetail;
  selectedStage: string;
  busy: boolean;
  onSelectStage: (stage: string) => void;
  onStart: (stage: string) => void;
  onCancel: (stage: string) => void;
  onRetry: (stage: string) => void;
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
  const keys = STAGE_DEFAULT_ORDER.filter((k) => job.stages[k]);

  const nodes: ReactNode[] = keys.map((k, idx) => (
    <Fragment key={k}>
      {idx > 0 ? <div className="pipeline-arrow">▼ 依赖上一阶段完成 ▼</div> : null}
      <StageCard
        stageKey={k}
        label={STAGE_LABELS[k] ?? k}
        detail={job.stages[k]}
        selected={k === selectedStage}
        busy={busy}
        onSelect={() => onSelectStage(k)}
        onStart={() => onStart(k)}
        onCancel={() => onCancel(k)}
        onRetry={() => onRetry(k)}
      />
    </Fragment>
  ));

  return (
    <div className="pipeline">
      <h3 className="panel-title">处理管线</h3>
      <div className="pipeline-col">{nodes}</div>
    </div>
  );
}