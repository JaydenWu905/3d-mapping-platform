import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';

import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import FullscreenExitRoundedIcon from '@mui/icons-material/FullscreenExitRounded';
import FullscreenRoundedIcon from '@mui/icons-material/FullscreenRounded';
import PlayCircleOutlineRoundedIcon from '@mui/icons-material/PlayCircleOutlineRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';

import { api, messageOf } from '../api/api';
import { ArtifactsPanel } from '../components/ArtifactsPanel';
import { Chart, useChart } from '../components/chart';
import { LogViewer } from '../components/LogViewer';
import {
  BACKEND_STATUS_LABELS,
  PipelineView,
  STAGE_LABELS,
} from '../components/PipelineView';
import {
  blockedReasonLabel,
  formatElapsed,
  progressLabel,
  progressBarState,
  stageMessageLabel,
  stagePhaseLabel,
  stageProgressText,
} from '../components/progressLabel';
import { StageProgressBar } from '../components/StageProgressBar';
import { StatusBadge } from '../components/StatusBadge';
import { WaitingPreview } from '../components/WaitingPreview';
import { hasUsablePreview } from '../components/waitingPreview/artifacts';
import { choosePreviewStage, deriveTaskPreview, initialPreviewChoice } from '../components/waitingPreview/taskPreviewState';
import { useJob } from '../hooks/useJob';
import { useObservedProgress } from '../hooks/useObservedProgress';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { isStageKey } from '../types';
import type { JobDetail, Manifest, StageDetail, StageKey } from '../types';
import { STAGE_NAMES, STAGE_ORDER, visibleStageKeys } from '../utils/jobDisplay';
import { EsdfViewer } from '../viewers/EsdfViewer';
import { MeshViewer } from '../viewers/MeshViewer';
import { TrajectoryViewer } from '../viewers/TrajectoryViewer';

const ACTIVE_STATUSES = ['running', 'queued', 'cancelling'];

const STAGE_COLORS: Record<StageKey, string> = {
  pose: '#1877F2',
  surface: '#8E33FF',
  distance: '#00B8D9',
};

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function manifestArtifact(stage: StageDetail, artifactId: string) {
  return stage.manifest?.artifacts?.find((a) => a.artifact_id === artifactId) ?? null;
}

function isActiveStage(stage: StageDetail): boolean {
  return ACTIVE_STATUSES.includes(stage.status);
}

/** 已有成果保留真实查看器的交互提示。 */
function previewHint(stage: StageDetail): string {
  if (hasUsablePreview(stage)) return '可旋转 · 缩放 · 平移 · 重置视角';
  if (stage.status === 'not_integrated') return '未请求该阶段';
  if (stage.status === 'failed' || stage.status === 'cancelled' || stage.status === 'completed') {
    return '无可用预览产物';
  }
  return '等待动画 · 非实时地图';
}

function validationText(scope: string | undefined): string {
  if (scope === 'ins_full_pose_surface') {
    return '本任务验收已验证 INS profile 的完整两阶段一键流程，不代表任意 bag 兼容或建图精度通过。';
  }
  if (scope === 'custom_device_pose_surface_unverified') {
    return '本任务使用自采设备配置；CPU 预检和参数匹配不代表 GLIM/MrHash 结果或精度已验收。';
  }
  if (scope === 'full_surface_only') {
    return '本任务仅验收完整表面重建，不代表完整一键流程或建图精度通过。';
  }
  return '短段成功不代表完整场景重建或精度验收。';
}

function poseScopeText(job: JobDetail): string {
  const pose = job.run_scope?.pose;
  if (pose === 'reused') return '复用已有真实位姿（本任务未运行位姿估计算法）';
  if (pose === 'full') return '完整序列';
  if (pose === 'registered') return '按注册轨迹';
  return '—';
}

export function JobDetailPage() {
  const { jobId = '' } = useParams();
  const { job, error, connected, refresh, actions } = useJob(jobId);
  const navigate = useNavigate();
  const [selectedStage, setSelectedStage] = useState<string>('pose');
  const [previewChoice, setPreviewChoice] = useState(() => initialPreviewChoice(jobId));
  const preview = deriveTaskPreview(job, previewChoice);
  const [datasetMeta, setDatasetMeta] = useState<{ dataset: string; execution: unknown } | null>(null);
  const [busy, setBusy] = useState(false);
  const [displayMode, setDisplayMode] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const everConnected = useRef(false);
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const dataset = job?.dataset;
    if (!dataset) return undefined;
    let cancelled = false;
    void api.getDatasets().then(datasets => {
      if (!cancelled) setDatasetMeta({ dataset, execution: datasets.find(item => item.id === dataset)?.input_manifest?.execution });
    }).catch(() => { /* 不影响任务和已有产物加载。 */ });
    return () => { cancelled = true; };
  }, [job?.dataset]);

  // 详情可以跟随正在看的阶段，但执行阶段始终独立从服务端派生。
  useEffect(() => {
    if (preview.viewStageKey) setSelectedStage(preview.viewStageKey);
  }, [jobId, preview.viewStageKey]);

  useEffect(() => {
    if (connected) everConnected.current = true;
  }, [connected]);

  // 选中阶段必须属于本任务请求范围；旧任务按 not_integrated 回退。
  useEffect(() => {
    if (!job) return;
    const visible = visibleStageKeys(job);
    if (isStageKey(selectedStage) && visible.includes(selectedStage)) return;
    const next = visible[0] ?? STAGE_ORDER.find((stage) => job.stages[stage]);
    if (next) setSelectedStage(next);
  }, [job, selectedStage]);

  useEffect(() => {
    if (!displayMode) return;

    document.body.classList.add('display-mode');
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDisplayMode(false);
    };
    window.addEventListener('keydown', onKeyDown);

    return () => {
      document.body.classList.remove('display-mode');
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [displayMode]);

  const stageKey = isStageKey(selectedStage) ? selectedStage : null;
  const stage = job && stageKey ? job.stages[stageKey] : null;
  const observed = useObservedProgress(
    job,
    stage && stage.status !== 'not_integrated' ? stageKey : null,
  );

  const observedCategories = observed.map((sample) =>
    new Date(sample.observedAt).toLocaleTimeString('zh-CN', { hour12: false }),
  );
  const inputSeries = observed.map((sample) =>
    sample.kind === 'input' ? Math.round(sample.percent) : null,
  );
  const stageSeries = observed.map((sample) =>
    sample.kind === 'stage' ? Math.round(sample.percent) : null,
  );

  const durations = useMemo(() => {
    if (!job) return [];
    return visibleStageKeys(job).flatMap((key) => {
      const detail = job.stages[key];
      const runtime = detail.manifest?.runtime_sec;
      if (typeof runtime !== 'number' || !Number.isFinite(runtime)) return [];
      return [
        {
          stage: key,
          label: STAGE_NAMES[key],
          value: Math.round(runtime * 10) / 10,
          color: STAGE_COLORS[key],
        },
      ];
    });
  }, [job]);

  const observedChartOptions = useChart({
    chart: { type: 'line', animations: { enabled: !reducedMotion, speed: 360 } },
    colors: ['#00B8D9', '#1877F2'],
    stroke: { width: 2.5, curve: 'smooth' },
    markers: { size: 3, strokeWidth: 0 },
    legend: {
      show: true,
      position: 'top',
      horizontalAlign: 'left',
      fontSize: '16px',
    },
    xaxis: {
      categories: observedCategories,
      labels: { style: { fontSize: '16px' }, rotate: 0, hideOverlappingLabels: true },
    },
    yaxis: {
      min: 0,
      max: 100,
      tickAmount: 5,
      labels: {
        style: { fontSize: '16px' },
        formatter: (value: number) => `${Math.round(value)}%`,
      },
    },
    tooltip: {
      y: { formatter: (value: number) => `${Math.round(value)}%` },
    },
    noData: { text: '暂无数据', style: { fontSize: '16px' } },
  });

  const durationChartOptions = useChart({
    chart: { type: 'bar', animations: { enabled: !reducedMotion, speed: 360 } },
    colors: durations.map((item) => item.color),
    plotOptions: {
      bar: { horizontal: true, distributed: true, barHeight: '52%', borderRadius: 0 },
    },
    dataLabels: {
      enabled: true,
      formatter: (value: string) => `${Math.round(Number(value))} 秒`,
      style: { fontSize: '14px', fontWeight: 600, colors: ['#ffffff'] },
    },
    stroke: { width: 0 },
    xaxis: {
      categories: durations.map((item) => item.label),
      labels: { style: { fontSize: '16px' } },
    },
    yaxis: { labels: { style: { fontSize: '16px' } } },
    grid: { xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
    legend: { show: false },
    tooltip: { y: { formatter: (value: number) => `${value} 秒` } },
    noData: { text: '暂无数据', style: { fontSize: '16px' } },
  });

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!job) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteJob(job.job_id);
      navigate('/');
    } catch (err: unknown) {
      setDeleteError(messageOf(err));
    } finally {
      setDeleting(false);
    }
  };

  if (!job) {
    if (error) {
      return (
        <Stack spacing={2} sx={{ py: 8 }}>
          <Alert
            severity="error"
            action={
              <Button color="inherit" size="small" onClick={() => void refresh()}>
                重试
              </Button>
            }
          >
            任务加载失败：{error}
          </Alert>
        </Stack>
      );
    }

    return (
      <Stack alignItems="center" spacing={2} sx={{ py: 12, color: 'text.secondary' }}>
        <CircularProgress size={28} />
        <Typography sx={{ fontSize: 16 }}>正在加载任务详情…</Typography>
      </Stack>
    );
  }

  const requestedStages = visibleStageKeys(job);
  const previewStage = preview.viewStageKey ? job.stages[preview.viewStageKey] : null;
  const activeStage = preview.activeStageKey ? job.stages[preview.activeStageKey] : null;
  const activeBar = activeStage ? progressBarState(activeStage) : null;
  const isDemo = (datasetMeta?.dataset === job.dataset && datasetMeta.execution === 'mock') || job.preview_job
    || Object.values(job.stages).some(item => item.manifest?.backend_details?.mock_backend === true);
  const missingResults = job.status === 'completed'
    ? requestedStages.filter(key => !hasUsablePreview(job.stages[key])) : [];
  const terminalIssue = requestedStages.find(key => ['failed', 'cancelled'].includes(job.stages[key].status));
  const twoStage = requestedStages.length === 2;
  const jobLocked =
    job.status === 'completed' || ['running', 'queued', 'cancelling'].includes(job.status);
  const connectionText = connected
    ? '实时连接已建立'
    : everConnected.current
      ? '连接中断，正在重连'
      : '正在建立实时连接…';

  return (
    <Box>
      <Card sx={{ p: 2, mb: 1.5, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'flex-start' }}>
          <Box sx={{ flex: '1 1 480px', minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography
                component="h1"
                sx={{
                  fontFamily: 'var(--mono)',
                  fontSize: 30,
                  fontWeight: 700,
                  lineHeight: 1.2,
                  wordBreak: 'break-all',
                }}
              >
                {job.job_id}
              </Typography>
              {isDemo ? (
                <Box
                  component="span"
                  sx={{
                    px: 0.75,
                    py: 0.1,
                    fontSize: 11,
                    color: 'warning.dark',
                    bgcolor: 'warning.lighter',
                    border: '1px solid',
                    borderColor: 'warning.main',
                  }}
                >
                  演示任务 · 合成数据
                </Box>
              ) : null}
              <StatusBadge status={job.status} size="medium" />
            </Stack>

            <Stack
              direction="row"
              spacing={2}
              flexWrap="wrap"
              useFlexGap
              className="job-meta"
              sx={{ mt: 1, color: 'text.secondary', rowGap: 0.5 }}
            >
              <Typography sx={{ fontSize: 14, display: 'flex', alignItems: 'baseline', gap: 0.75, flexWrap: 'wrap' }}>
                数据集 <Box component="strong" sx={{ color: 'text.primary', fontSize: 18, fontWeight: 700, overflowWrap: 'anywhere' }}>{job.dataset}</Box>
              </Typography>
              <Typography sx={{ fontSize: 14, display: 'flex', alignItems: 'baseline', gap: 0.75, flexWrap: 'wrap' }}>
                创建于 <Box component="strong" sx={{ color: 'text.primary', fontSize: 18, fontWeight: 700 }}>{formatDate(job.created_at)}</Box>
              </Typography>
            </Stack>

            <Stack
              direction="row"
              spacing={0.75}
              alignItems="center"
              aria-live="polite"
              sx={{ mt: 1 }}
            >
              <Box
                sx={{
                  width: 8,
                  height: 8,
                  flex: 'none',
                  bgcolor: connected
                    ? 'success.main'
                    : everConnected.current
                      ? 'error.main'
                      : 'warning.main',
                }}
              />
              <Typography
                sx={{
                  fontSize: 14,
                  color: connected ? 'success.dark' : 'text.secondary',
                }}
              >
                {connectionText}
              </Typography>
            </Stack>
            {job.fail_stage ? (
              <Typography sx={{ mt: 0.5, fontSize: 14 }}>
                模拟失败阶段{' '}
                <Box component="strong" sx={{ color: 'error.main' }}>
                  {isStageKey(job.fail_stage) ? STAGE_NAMES[job.fail_stage] : job.fail_stage}
                </Box>
              </Typography>
            ) : null}
          </Box>

          <Stack
            direction="row"
            spacing={1}
            flexWrap="wrap"
            useFlexGap
            sx={{ flex: '0 1 auto', justifyContent: { xs: 'flex-start', lg: 'flex-end' } }}
          >
            <Button
              variant="outlined"
              startIcon={displayMode ? <FullscreenExitRoundedIcon /> : <FullscreenRoundedIcon />}
              onClick={() => setDisplayMode((value) => !value)}
              title={displayMode ? '退出展示模式（Esc）' : '隐藏导航与详细日志，放大查看器'}
            >
              {displayMode ? '退出展示模式' : '展示模式'}
            </Button>
            <Button
              variant="contained"
              startIcon={<PlayCircleOutlineRoundedIcon />}
              onClick={() =>
                void run(() => (twoStage ? actions.runPlanned() : actions.runAll()))
              }
              disabled={busy || jobLocked}
            >
              {twoStage ? '一键运行（位姿估计 → 表面重建）' : '一键运行（全部阶段）'}
            </Button>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => void refresh()}
              disabled={busy || deleting}
            >
              刷新
            </Button>
            <Button
              variant="outlined"
              color="error"
              startIcon={<DeleteOutlineRoundedIcon />}
              onClick={() => {
                setDeleteError(null);
                setDeleteOpen(true);
              }}
              disabled={busy || deleting}
            >
              删除
            </Button>
          </Stack>
        </Box>
      </Card>

      {error ? (
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => void refresh()}>
              重试
            </Button>
          }
          sx={{ mb: 1.5 }}
        >
          操作失败：{error}
        </Alert>
      ) : null}

      <Card sx={{ p: 2, mb: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
        <PipelineView
          job={job}
          selectedStage={selectedStage}
          busy={busy}
          onSelectStage={key => {
            setSelectedStage(key);
            if (isStageKey(key)) setPreviewChoice(choosePreviewStage(job, key));
          }}
          onStart={(key) => void run(() => actions.startStage(key))}
          onCancel={(key) => void run(() => actions.cancelStage(key))}
          onRetry={(key) => void run(() => actions.retryStage(key))}
        />
      </Card>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: '7fr 3fr' },
          gap: 2,
          alignItems: 'start',
        }}
      >
        <Box
          className="detail-viewer"
          data-preview-mode={preview.mode}
          data-active-stage={preview.activeStageKey ?? ''}
          data-view-stage={preview.viewStageKey ?? ''}
          sx={{
            minWidth: 0,
            bgcolor: 'background.paper',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Box className="task-preview-live" role="status" aria-live="polite">
            <Typography component="strong">
              {activeStage ? `后台正在执行：${STAGE_NAMES[activeStage.stage as StageKey]}`
                : terminalIssue ? `${STAGE_NAMES[terminalIssue]}${job.stages[terminalIssue].status === 'failed' ? '运行失败' : '已取消'}，已有成果仍可查看`
                : job.status === 'completed' ? '任务已完成' : job.status === 'running' ? '正在衔接下一阶段…' : '任务尚未开始'}
            </Typography>
            {activeStage ? <Typography>{stagePhaseLabel(activeStage)}{activeBar?.percent != null ? ` · ${activeBar.kind === 'input' ? '输入发布' : '阶段进度'} ${Math.round(activeBar.percent)}%` : ' · 进度未上报'}</Typography> : null}
            {!connected && everConnected.current ? <Typography color="warning.main">连接中断，正在重连</Typography> : null}
          </Box>
          {missingResults.length ? <Alert severity="warning" sx={{ borderRadius: 0 }}>{missingResults.map(key => STAGE_NAMES[key]).join('、')}已完成但缺少可用预览，请检查产物清单。</Alert> : null}
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ px: 2, py: 1.25, borderBottom: '1px solid', borderColor: 'divider' }}
          >
            <Typography sx={{ fontSize: 16, fontWeight: 700 }}>三维预览</Typography>
            <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
              {previewStage ? STAGE_NAMES[previewStage.stage as StageKey] : ''}
            </Typography>
            <Box sx={{ flex: 1 }} />
            <Typography sx={{ fontSize: 12, color: 'text.disabled' }}>
              {previewStage ? preview.mode === 'results' ? previewHint(previewStage) : '自动小车 · 非实时地图' : ''}
            </Typography>
          </Stack>

          <Box className="task-preview-toolbar">
            <ToggleButtonGroup exclusive size="small" value={preview.mode} aria-label="预览内容" onChange={(_event, mode: 'animation' | 'results' | null) => {
              if (!mode) return;
              setPreviewChoice({ jobId, mode, resultStageKey: preview.resultStageKey, animationStageKey: null });
            }}>
              <ToggleButton value="animation" data-preview-mode-button="animation" disabled={job.status === 'completed' && !activeStage && preview.availableResults.length > 0}>实时进度</ToggleButton>
              <ToggleButton value="results" data-preview-mode-button="results" disabled={!preview.availableResults.length}>已有成果{preview.availableResults.length ? `（${preview.availableResults.length}）` : ''}</ToggleButton>
            </ToggleButtonGroup>
            {!preview.availableResults.length ? <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>成果生成后即可切换查看</Typography> : null}
            {preview.mode === 'results' ? <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap aria-label="选择已有成果">
              {preview.availableResults.map(key => <Button key={key} size="small" data-result-stage={key} aria-pressed={preview.resultStageKey === key} variant={preview.resultStageKey === key ? 'contained' : 'outlined'} onClick={() => {
                setPreviewChoice({ jobId, mode: 'results', resultStageKey: key, animationStageKey: null });
                setSelectedStage(key);
              }}>{STAGE_NAMES[key]}</Button>)}
            </Stack> : null}
            {isDemo ? <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>后台演示任务 · 每阶段约30秒 · 成果为预制合成示例</Typography> : null}
          </Box>

          <Box sx={{ p: 1.5, minWidth: 0 }}>
            {previewStage ? (
              <StageViewer
                key={`${job.job_id}:${previewStage.stage}:${preview.mode}`}
                jobId={job.job_id}
                stage={previewStage}
                manifest={previewStage.manifest}
                connected={connected}
                waitingOnly={preview.mode === 'animation'}
              />
            ) : (
              <Box className="viewer-empty">该任务没有阶段信息。</Box>
            )}
            {preview.mode === 'results' && previewStage?.stage === 'surface' && previewStage.manifest?.metrics ? (
              <PreviewNote metrics={previewStage.manifest.metrics} />
            ) : null}
          </Box>
        </Box>

        <Stack className="detail-summary" spacing={2} sx={{ minWidth: 0 }}>
          {stage ? (
            <Card
              sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}
            >
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography sx={{ fontSize: 22, fontWeight: 700 }}>
                  {STAGE_NAMES[stage.stage as StageKey] ?? STAGE_LABELS[stage.stage] ?? stage.stage}
                </Typography>
                <StatusBadge status={stage.status} size="medium" />
                <Box sx={{ flex: 1 }} />
                <Typography sx={{ fontSize: 12, color: 'text.disabled' }}>
                  阶段 {Math.max(1, requestedStages.indexOf(stage.stage as StageKey) + 1)} /{' '}
                  {requestedStages.length || '—'}
                </Typography>
              </Stack>

              <Stack spacing={0.75} sx={{ mt: 1.5 }}>
                <InfoRow
                  label="阶段算法"
                  value={
                    <>
                      <Box component="span" sx={{ fontWeight: 600 }}>
                        {stage.backend_display || stage.backend || '未选择'}
                      </Box>
                      <Box component="span" sx={{ color: 'text.secondary' }}>
                        {' '}
                        · {BACKEND_STATUS_LABELS[stage.backend_status] ?? stage.backend_status}
                      </Box>
                    </>
                  }
                />
                <InfoRow label="当前环节" value={stagePhaseLabel(stage)} />
                <InfoRow label="阶段耗时" value={formatElapsed(stage.elapsed_sec)} />
              </Stack>

              <Box sx={{ mt: 1.75 }}>
                <StageProgressBar stage={stage} large />
                <Stack
                  direction="row"
                  spacing={1}
                  justifyContent="space-between"
                  sx={{ mt: 0.75 }}
                >
                  <Typography sx={{ fontSize: 14, color: 'text.secondary', minWidth: 0 }}>
                    {progressLabel(stage)}
                  </Typography>
                  <Typography sx={{ flex: 'none', fontSize: 14, color: 'text.secondary' }}>
                    {stageProgressText(stage)}
                  </Typography>
                </Stack>
                <Typography
                  title={stage.message}
                  sx={{
                    mt: 0.75,
                    fontSize: 13,
                    color: 'text.secondary',
                    wordBreak: 'break-word',
                  }}
                >
                  {stageMessageLabel(stage)}
                </Typography>
                {!stage.can_run && stage.run_blocked_reason ? (
                  <Alert severity="warning" sx={{ mt: 1.25 }}>
                    当前阶段不可运行：{blockedReasonLabel(stage.run_blocked_reason)}
                  </Alert>
                ) : null}
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography sx={{ fontSize: 16, fontWeight: 700 }}>
                本次页面观测的进度
              </Typography>
              <Chart
                type="line"
                className="detail-observe-chart"
                series={[
                  { name: '输入发布进度', data: inputSeries },
                  { name: '阶段进度', data: stageSeries },
                ]}
                options={observedChartOptions}
                sx={{ height: 220, mt: 1 }}
              />
              <Typography sx={{ mt: 0.5, fontSize: 12, color: 'text.disabled' }}>
                只记录本页面打开后的真实读数；刷新页面后重新观测，不补造历史。
              </Typography>

              <Divider sx={{ my: 2 }} />

              <Typography sx={{ fontSize: 16, fontWeight: 700 }}>各阶段耗时</Typography>
              <Chart
                type="bar"
                className="detail-duration-chart"
                series={[{ name: '耗时（秒）', data: durations.map((item) => item.value) }]}
                options={durationChartOptions}
                sx={{ height: 190, mt: 1 }}
              />
              <Typography sx={{ mt: 0.5, fontSize: 12, color: 'text.disabled' }}>
                仅展示已完成阶段产物清单中的真实运行耗时。
              </Typography>
            </Card>
          ) : (
            <Card sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
              <Typography sx={{ fontSize: 16, color: 'text.secondary' }}>
                该任务没有可展示的阶段信息。
              </Typography>
            </Card>
          )}
        </Stack>
      </Box>

      <Box
        className="detail-secondary"
        sx={{
          mt: 2,
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', xl: 'repeat(2, minmax(0, 1fr))' },
          gap: 2,
          alignItems: 'start',
        }}
      >
        <CollapsibleSection
          title="产物、完整指标与算法细节"
          summary="按当前阶段展示 manifest 中的产物、指标和后端细节。"
        >
          {stage ? (
            <ArtifactsPanel
              jobId={job.job_id}
              stage={stage.stage as StageKey}
              manifest={stage.manifest}
            />
          ) : null}
        </CollapsibleSection>

        <CollapsibleSection
          title="运行日志"
          summary="查看当前阶段日志；阶段运行时自动刷新。"
        >
          {stage ? (
            <LogViewer
              jobId={job.job_id}
              stage={stage.stage as StageKey}
              active={isActiveStage(stage)}
            />
          ) : null}
        </CollapsibleSection>

        <CollapsibleSection
          title="设备与算法配置"
          summary="设备配置、阶段算法、复用位姿与运行模式。"
        >
          <Stack spacing={1}>
            {job.device_config ? (
              <>
                <InfoRow label="配置 ID" value={job.device_config.id} mono />
                <InfoRow label="配置版本" value={job.device_config.version} mono />
                <InfoRow
                  label="配置 SHA-256"
                  value={job.device_config.sha256 || '—'}
                  mono
                />
                <InfoRow
                  label="实际参数"
                  value={job.device_config.effective_params}
                  mono
                />
                <InfoRow label="配置快照" value={job.device_config.snapshot} mono />
              </>
            ) : (
              <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
                本任务未绑定设备配置。
              </Typography>
            )}

            <Divider sx={{ my: 0.5 }} />
            {STAGE_ORDER.map((key) =>
              job.backends[key] ? (
                <InfoRow
                  key={key}
                  label={STAGE_NAMES[key]}
                  value={job.backends[key] ?? '—'}
                  mono
                />
              ) : null,
            )}
            <InfoRow label="运行模式" value={job.run_mode === 'short' ? '短段' : '完整序列'} />
            <InfoRow
              label="请求阶段"
              value={requestedStages.map((key) => STAGE_NAMES[key]).join(' → ') || '—'}
            />
            {job.pose_reuse ? (
              <>
                <InfoRow label="位姿复用" value={job.pose_reuse.label} />
                <InfoRow
                  label="来源任务"
                  value={job.pose_reuse.source_job_id}
                  mono
                />
                <InfoRow label="位姿 SHA-256" value={job.pose_reuse.sha256} mono />
              </>
            ) : null}
            {job.fail_stage ? (
              <InfoRow
                label="模拟失败"
                value={
                  isStageKey(job.fail_stage)
                    ? STAGE_NAMES[job.fail_stage]
                    : job.fail_stage
                }
              />
            ) : null}

            {stage ? (
              <>
                <Divider sx={{ my: 0.5 }} />
                <Typography sx={{ fontSize: 13, color: 'text.disabled' }}>
                  后端原始技术字段（保留原文，便于排查）
                </Typography>
                <InfoRow label="阶段键" value={stage.stage} mono />
                <InfoRow label="后端 phase" value={stage.phase || '—'} mono />
                <InfoRow label="后端 message" value={stage.message || '—'} mono />
                <InfoRow
                  label="不可启动原因"
                  value={stage.run_blocked_reason || '—'}
                  mono
                />
              </>
            ) : null}
          </Stack>
        </CollapsibleSection>

        <CollapsibleSection
          title="运行范围与验收说明"
          summary="包含运行范围、标定依据、预览简化与本次验收边界。"
        >
          <Stack spacing={1.25}>
            {requestedStages.includes('distance') ? null : (
              <Typography sx={{ fontSize: 15, fontWeight: 600 }}>
                本任务未请求距离场。
              </Typography>
            )}
            <InfoRow
              label="位姿范围"
              value={job.run_scope ? poseScopeText(job) : '—'}
            />
            <InfoRow
              label="表面帧范围"
              value={
                job.run_scope
                  ? `原始第 ${job.run_scope.surface_start_frame}–${
                      job.run_scope.surface_end_frame ?? '末尾'
                    } 帧`
                  : '—'
              }
            />
            <Typography sx={{ fontSize: 14, lineHeight: 1.7, color: 'text.secondary' }}>
              {validationText(job.validation_scope)}
            </Typography>
            <Typography sx={{ fontSize: 14, lineHeight: 1.7, color: 'text.secondary' }}>
              标定与预检说明：设备外参及 IMU 单位依据仍需确认；CPU 预检只验证数据结构与配置条件，不代表算法成功或精度合格。
            </Typography>
            {stage?.stage === 'surface' &&
            stage.manifest?.metrics?.preview_simplification_applied === true ? (
              <Typography sx={{ fontSize: 14, lineHeight: 1.7, color: 'text.secondary' }}>
                浏览器 GLB 预览已简化：
                {String(stage.manifest.metrics.preview_source_faces ?? '—')} →{' '}
                {String(stage.manifest.metrics.preview_faces ?? '—')}{' '}
                面。简化可能改变细小分量与边界；完整原生 Mesh 可在上方产物区下载。
              </Typography>
            ) : null}
          </Stack>
        </CollapsibleSection>
      </Box>

      <Dialog
        open={deleteOpen}
        onClose={() => {
          if (!deleting) setDeleteOpen(false);
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>删除任务</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ fontSize: 16 }}>
            确认删除任务 <Box component="code">{job.job_id}</Box> ？
            该操作会删除其磁盘上的所有数据，且不可恢复。
          </DialogContentText>
          {deleteError ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              删除失败：{deleteError}
            </Alert>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)} disabled={deleting}>
            取消
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void confirmDelete()}
            disabled={deleting}
          >
            {deleting ? '删除中…' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ minWidth: 0 }}>
      <Typography
        sx={{ flex: 'none', width: 96, fontSize: 14, color: 'text.secondary' }}
      >
        {label}
      </Typography>
      <Typography
        sx={{
          minWidth: 0,
          fontSize: 14,
          wordBreak: 'break-all',
          fontFamily: mono ? 'var(--mono)' : undefined,
        }}
      >
        {value}
      </Typography>
    </Stack>
  );
}

function CollapsibleSection({
  title,
  summary,
  children,
}: {
  title: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <Box
      component="section"
      sx={{ bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider' }}
    >
      <Box
        component="details"
        sx={{ '&[open] .collapse-arrow': { transform: 'rotate(90deg)' } }}
      >
        <Box
          component="summary"
          sx={{
            p: 1.75,
            display: 'flex',
            alignItems: 'center',
            gap: 1.25,
            cursor: 'pointer',
            listStyle: 'none',
            '&::-webkit-details-marker': { display: 'none' },
          }}
        >
          <ChevronRightRoundedIcon
            className="collapse-arrow"
            sx={{
              flex: 'none',
              fontSize: 20,
              color: 'text.secondary',
              transition: 'transform .2s ease',
            }}
          />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontSize: 18, fontWeight: 700 }}>{title}</Typography>
            <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>{summary}</Typography>
          </Box>
          <Typography sx={{ flex: 'none', fontSize: 12, color: 'text.disabled' }}>
            展开 / 收起
          </Typography>
        </Box>
        <Box sx={{ px: 1.75, pb: 2 }}>{children}</Box>
      </Box>
    </Box>
  );
}

function PreviewNote({ metrics }: { metrics: Record<string, unknown> }) {
  if (metrics.preview_simplification_applied !== true) return null;

  return (
    <Box
      component="details"
      sx={{ mt: 1.5, border: '1px solid', borderColor: 'divider', bgcolor: 'background.neutral' }}
    >
      <Box
        component="summary"
        sx={{
          px: 1.25,
          py: 0.9,
          cursor: 'pointer',
          fontSize: 14,
          color: 'text.secondary',
          listStyle: 'none',
          '&::-webkit-details-marker': { display: 'none' },
        }}
      >
        预览简化说明
      </Box>
      <Typography sx={{ px: 1.25, pb: 1.25, fontSize: 14, lineHeight: 1.7 }}>
        浏览器 GLB 预览已简化：{String(metrics.preview_source_faces ?? '—')} →{' '}
        {String(metrics.preview_faces ?? '—')} 面。简化可能改变细小分量与边界；完整原生
        Mesh 可在下方“产物、完整指标与算法细节”中下载。
      </Typography>
    </Box>
  );
}

function StageViewer({
  jobId,
  stage,
  manifest,
  connected,
  waitingOnly,
}: {
  jobId: string;
  stage: StageDetail;
  manifest: Manifest | null;
  connected: boolean;
  waitingOnly: boolean;
}) {
  const slices = useMemo(() => {
    const value = manifest?.metrics?.slices;
    return Array.isArray(value) ? (value as string[]).map(String) : [];
  }, [manifest]);

  const hasTraj = manifestArtifact(stage, 'trajectory_model') !== null;

  if (waitingOnly) return <WaitingPreview stage={stage} connected={connected} runKey={`${jobId}:${stage.stage}:${stage.started_at ?? 'pending'}`} />;

  // 查看器按阶段键固定映射（架构约束：不按算法分支）。
  if (stage.stage === 'pose') {
    if (hasTraj) return <TrajectoryViewer jobId={jobId} stage={stage.stage} />;
    return <WaitingPreview stage={stage} connected={connected} runKey={`${jobId}:${stage.stage}:${stage.started_at ?? 'pending'}`} />;
  }

  if (stage.stage === 'surface') {
    const artifact = manifestArtifact(stage, 'surface_model');
    if (artifact) {
      const revision = String(stage.manifest?.metrics?.preview_sha256 ?? '');
      return (
        <MeshViewer
          url={api.previewUrl(jobId, stage.stage, artifact.artifact_id, revision)}
        />
      );
    }
    return <WaitingPreview stage={stage} connected={connected} runKey={`${jobId}:${stage.stage}:${stage.started_at ?? 'pending'}`} />;
  }

  if (stage.stage === 'distance') {
    if (hasUsablePreview(stage)) {
      return (
        <EsdfViewer
          jobId={jobId}
          stage={stage.stage}
          slices={slices}
          artifacts={manifest?.artifacts ?? []}
        />
      );
    }
    return <WaitingPreview stage={stage} connected={connected} runKey={`${jobId}:${stage.stage}:${stage.started_at ?? 'pending'}`} />;
  }

  return null;
}
