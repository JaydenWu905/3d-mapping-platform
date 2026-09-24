import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/api';
import { useJob } from '../hooks/useJob';
import { isStageKey } from '../types';
import type { Manifest, StageDetail, StageKey } from '../types';
import { StatusBadge } from '../components/StatusBadge';
import { PipelineView, STAGE_LABELS } from '../components/PipelineView';
import { LogViewer } from '../components/LogViewer';
import { ArtifactsPanel } from '../components/ArtifactsPanel';
import { TrajectoryViewer } from '../viewers/TrajectoryViewer';
import { MeshViewer } from '../viewers/MeshViewer';
import { EsdfViewer } from '../viewers/EsdfViewer';

const STAGE_ORDER: StageKey[] = ['pose', 'surface', 'distance'];

function formatElapsed(sec: number): string {
  if (!sec) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function manifestArtifact(stage: StageDetail, artifactId: string) {
  return stage.manifest?.artifacts?.find((a) => a.artifact_id === artifactId) ?? null;
}

export function JobDetailPage() {
  const { jobId = '' } = useParams();
  const { job, error, connected, refresh, actions } = useJob(jobId);
  const navigate = useNavigate();
  const [selectedStage, setSelectedStage] = useState<string>('pose');
  const [busy, setBusy] = useState(false);

  // 当 job 首次加载 / 刷新时，保证选中的阶段存在。
  useEffect(() => {
    if (job && !(isStageKey(selectedStage) && job.stages[selectedStage])) {
      const k = STAGE_ORDER.find((s) => job.stages[s]);
      if (k) setSelectedStage(k);
    }
  }, [job, selectedStage]);

  const stage = job && isStageKey(selectedStage) ? job.stages[selectedStage] : null;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const deleteJob = async () => {
    if (!job) return;
    if (!window.confirm(`确认删除任务 ${job.job_id} ？该操作会删除其磁盘上的所有数据。`)) return;
    await run(() => actions.deleteJob());
    navigate('/');
  };

  if (!job) {
    return (
      <div className="page">
        {error ? <div className="alert alert-error">{error}</div> : <div className="panel-empty">加载任务中…</div>}
      </div>
    );
  }

  const stageRunning = (s: StageDetail) => s.status === 'running' || s.status === 'cancelling';

  return (
    <div className="page">
      <div className="job-head">
        <div className="job-title">
          <h2>
            <code>{job.job_id}</code>
            {job.preview_job ? <span className="tag tag-demo">演示任务</span> : null}
          </h2>
          <div className="job-sub">
            数据集 <strong>{job.dataset}</strong> · 创建于 {new Date(job.created_at).toLocaleString('zh-CN', { hour12: false })}
            {job.fail_stage ? <> · 模拟失败阶段 <strong>{job.fail_stage}</strong></> : null}
          </div>
        </div>
        <div className="job-head-right">
          <span className={`sse-dot ${connected ? 'on' : ''}`} title={connected ? 'SSE 已连接' : 'SSE 未连接'} />
          <span className="job-status-big">
            <StatusBadge status={job.status} />
          </span>
          <button className="btn btn-primary" onClick={() => run(() => actions.runAll())} disabled={busy}>
            ▶ Run All
          </button>
          <button className="btn btn-ghost" onClick={() => refresh()} disabled={busy}>
            ↻ 刷新
          </button>
          <button className="btn btn-danger" onClick={() => void deleteJob()} disabled={busy}>
            删除
          </button>
        </div>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <div className="detail-grid">
        <aside className="detail-pipeline">
          <PipelineView
            job={job}
            selectedStage={selectedStage}
            busy={busy}
            onSelectStage={setSelectedStage}
            onStart={(s) => run(() => actions.startStage(s))}
            onCancel={(s) => run(() => actions.cancelStage(s))}
            onRetry={(s) => run(() => actions.retryStage(s))}
          />
        </aside>

        <div className="detail-main">
          {stage ? <StagePanel jobId={job.job_id} stage={stage} running={stageRunning(stage)} /> : <div className="panel-empty">该任务没有阶段信息。</div>}
        </div>
      </div>
    </div>
  );
}

function StagePanel({ jobId, stage, running }: { jobId: string; stage: StageDetail; running: boolean }) {
  const manifest = stage.manifest as Manifest | null;
  const slices = useMemo(() => {
    const v = manifest?.metrics?.slices;
    return Array.isArray(v) ? (v as string[]).map(String) : [];
  }, [manifest]);

  const stageInfo = (
    <div className="stage-info">
      <div className="stage-info-row">
        <h3 className="panel-title-inline">{STAGE_LABELS[stage.stage] ?? stage.stage}</h3>
        <StatusBadge status={stage.status} />
        <span className="muted">
          {stage.backend_display || stage.backend} · {stage.phase}
        </span>
        <span className="muted">⏱ {formatElapsed(stage.elapsed_sec)}</span>
      </div>
      <div className="progress-bg progress-lg">
        <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, stage.progress))}%` }} />
      </div>
      <div className="progress-meta">
        <span>
          {stage.current} / {stage.total} {stage.unit || ''}
        </span>
        <span>{Math.round(stage.progress)}% · {stage.message}</span>
      </div>
    </div>
  );

  return (
    <div className="stage-panel">
      {stageInfo}
      <StageViewer jobId={jobId} stage={stage} manifest={manifest} slices={slices} running={running} />
      <ArtifactsPanel jobId={jobId} stage={stage.stage} manifest={manifest} />
      <LogViewer jobId={jobId} stage={stage.stage} active={running} />
    </div>
  );
}

function StageViewer({
  jobId,
  stage,
  manifest,
  slices,
  running,
}: {
  jobId: string;
  stage: StageDetail;
  manifest: Manifest | null;
  slices: string[];
  running: boolean;
}) {
  const hasTraj = manifestArtifact(stage, 'trajectory_model') !== null;

  if (running && !manifest) {
    return <div className="viewer-empty">阶段运行中，完成后自动生成 3D 预览…</div>;
  }

  // 查看器按阶段键固定映射（架构约束：不按算法分支）。
  if (stage.stage === 'pose') {
    if (hasTraj) return <TrajectoryViewer jobId={jobId} stage={stage.stage} />;
    return <div className="viewer-empty">Pose 阶段暂无轨迹预览（manifest 中缺 trajectory_model）。</div>;
  }

  if (stage.stage === 'surface') {
    const a = manifestArtifact(stage, 'surface_model');
    if (a) {
      const revision = String(stage.manifest?.metrics?.preview_sha256 ?? '');
      return <MeshViewer url={api.previewUrl(jobId, stage.stage, a.artifact_id, revision)} />;
    }
    return <div className="viewer-empty">Surface 阶段暂无网格预览（manifest 中缺 surface_model）。</div>;
  }

  if (stage.stage === 'distance') {
    return (
      <EsdfViewer
        jobId={jobId}
        stage={stage.stage}
        slices={slices}
        artifacts={manifest?.artifacts ?? []}
      />
    );
  }

  return null;
}
