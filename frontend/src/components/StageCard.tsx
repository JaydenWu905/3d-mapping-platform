import type { StageDetail } from '../types';
import { StatusBadge } from './StatusBadge';
import { BACKEND_STATUS_LABELS } from './PipelineView';

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

function formatElapsed(sec: number): string {
  if (!sec) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function StageCard({ stageKey, label, detail, selected, busy, onSelect, onStart, onCancel, onRetry }: StageCardProps) {
  const running = detail.status === 'running' || detail.status === 'cancelling';
  const progress = Math.max(0, Math.min(100, detail.progress ?? 0));

  return (
    <div
      className={`stage-card ${selected ? 'selected' : ''} ${running ? 'active' : ''}`}
      onClick={() => onSelect()}
    >
      <div className="stage-card-head">
        <div className="stage-title">
          <span className="stage-index">
            {stageKey === 'pose' ? '①' : stageKey === 'surface' ? '②' : '③'}
          </span>
          <span className="stage-name">{label}</span>
        </div>
        <StatusBadge status={detail.status} />
      </div>

      <div className="stage-backend" title={`backend: ${detail.backend}`}>
        算法：<strong>{detail.backend_display || detail.backend || '未选择'}</strong>
        {' · '}状态 {BACKEND_STATUS_LABELS[detail.backend_status] ?? detail.backend_status}
      </div>

      <div className="stage-progress" title={detail.phase || detail.message || ''}>
        <div className="progress-bg">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <div className="progress-meta">
          <span>
            {detail.current} / {detail.total} {detail.unit || ''}
          </span>
          <span>{Math.round(progress)}%</span>
        </div>
      </div>

      <div className="stage-line">
        <span className="phase" title={detail.message}>
          {detail.phase || '待命'}
        </span>
        <span className="elapsed">⏱ {formatElapsed(detail.elapsed_sec)}</span>
      </div>

      {detail.message ? <div className="stage-message">{detail.message}</div> : null}

      <div className="stage-btns" onClick={(e) => e.stopPropagation()}>
        <StageButton
          detail={detail}
          busy={busy}
          onStart={onStart}
          onCancel={onCancel}
          onRetry={onRetry}
        />
      </div>
    </div>
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

  if (status === 'running' || status === 'cancelling') {
    return (
      <button className="btn btn-danger" onClick={onCancel} disabled={busy}>
        {status === 'cancelling' ? '取消中…' : '取消'}
      </button>
    );
  }

  if (status === 'completed' || status === 'failed' || status === 'cancelled') {
    return (
      <button className="btn btn-ghost" onClick={onRetry} disabled={busy}>
        ↻ 重跑
      </button>
    );
  }

  if (!can_run) {
    return (
      <span className="btn-disabled-hint" title={run_blocked_reason}>
        不可启动 · {run_blocked_reason}
      </span>
    );
  }

  return (
    <button className="btn btn-primary" onClick={onStart} disabled={busy}>
      ▶ 启动
    </button>
  );
}