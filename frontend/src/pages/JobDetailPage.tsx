import { progressLabel, posePhaseLabel, stageProgressText } from '../components/progressLabel';
import { StageProgressBar } from '../components/StageProgressBar';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/api';
import { useJob } from '../hooks/useJob';
import { isStageKey } from '../types';
import type { JobDetail, Manifest, StageDetail, StageKey } from '../types';
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
          <button className="btn btn-primary" onClick={() => run(() => job.requested_stages?.length === 2 ? actions.runPlanned() : actions.runAll())} disabled={busy || job.status === 'running' || job.status === 'completed'}>
            ▶ {job.requested_stages?.length === 2 ? '运行 Pose → Surface' : 'Run All'}
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
      {job.requested_stages?.length === 2 ? <div className="alert">运行范围：Pose {job.run_scope?.pose === 'reused' ? '复用已有真实 Pose（本任务未运行 GLIM）' : job.run_scope?.pose === 'full' ? '完整序列' : '按注册轨迹'}；Surface 原始第 {job.run_scope?.surface_start_frame ?? 1}–{job.run_scope?.surface_end_frame ?? '末尾'} 帧。本 Job 未请求 Distance。{job.validation_scope === 'ins_full_pose_surface' ? '本任务验收已验证 INS profile 的完整两阶段一键流程，不代表任意 bag 兼容或建图精度通过。外参及 IMU 单位依据待确认。' : job.validation_scope === 'custom_device_pose_surface_unverified' ? '本任务使用自采设备配置；CPU 预检和参数匹配不代表 GLIM/MrHash 结果或精度已验收。' : job.validation_scope === 'full_surface_only' ? '本任务仅验收完整 Surface，不代表完整一键流程或建图精度通过。外参及 IMU 单位依据待确认。' : '短段成功不代表完整场景重建或精度验收。'}</div> : null}

      {job.pose_reuse ? <div className="alert">复用已有真实 Pose · 来源 Job <code>{job.pose_reuse.source_job_id}</code> · poses.txt SHA-256 <code>{job.pose_reuse.sha256}</code></div> : null}
      {job.device_config ? <div className="alert">本 Job 设备配置：<code>{job.device_config.id}</code> · 版本 <code>{job.device_config.version}</code> · 实际参数已保存于 <code>{job.device_config.effective_params}</code></div> : null}

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
          {stage ? <StagePanel jobId={job.job_id} stage={stage} running={stageRunning(stage)} scope={job.run_scope} /> : <div className="panel-empty">该任务没有阶段信息。</div>}
        </div>
      </div>
    </div>
  );
}

function StagePanel({ jobId, stage, running, scope }: { jobId: string; stage: StageDetail; running: boolean; scope?: JobDetail['run_scope'] }) {
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
          {stage.backend_display || stage.backend} · {stage.stage === 'pose' && stage.backend === 'glim' ? posePhaseLabel(stage) : stage.phase}
        </span>
        <span className="muted">⏱ {formatElapsed(stage.elapsed_sec)}</span>
      </div>
      <StageProgressBar stage={stage} large />
      <div className="progress-meta">
        <span>
          {progressLabel(stage)}
        </span>
        <span>{stageProgressText(stage)} · {stage.message}</span>
      </div>
      {stage.stage === 'surface' && manifest?.metrics ? <div className="stage-message">
        全包 LiDAR {String(manifest.metrics.bag_lidar_frames ?? '—')} 帧 · 原始范围第 {scope?.surface_start_frame ?? 1}–{scope?.surface_end_frame ?? '末尾'} 帧 · 选中 {String(manifest.metrics.selected_frames ?? '—')} · 关联 {String(manifest.metrics.matched_pose_frames ?? '—')} · 融合 {String(manifest.metrics.fused_frames ?? '—')} · 跳过无 Pose {String(manifest.metrics.skipped_no_pose_frames ?? '—')}
      </div> : null}
    </div>
  );

  return (
    <div className="stage-panel">
      {stageInfo}
      {stage.stage === 'surface' && manifest?.metrics?.preview_simplification_applied === true ? <div className="alert">浏览器 GLB 预览已简化：{String(manifest.metrics.preview_source_faces)} → {String(manifest.metrics.preview_faces)} 面。简化可能改变细小分量与边界；完整原生 Mesh 可在下方下载。</div> : null}
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
