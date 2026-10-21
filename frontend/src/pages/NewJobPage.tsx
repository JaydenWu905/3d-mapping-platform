import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import Checkbox from '@mui/material/Checkbox';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Radio from '@mui/material/Radio';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded';
import RocketLaunchRoundedIcon from '@mui/icons-material/RocketLaunchRounded';

import { api, messageOf } from '../api/api';
import { BACKEND_STATUS_LABELS } from '../components/PipelineView';
import type { BackendDef, BackendsResponse, DatasetInfo, StageKey } from '../types';
import { STAGE_NAMES, STAGE_ORDER } from '../utils/jobDisplay';

export function datasetModalities(ds: DatasetInfo | undefined): Set<string> {
  const declared = ds?.input_manifest?.modalities;
  if (Array.isArray(declared)) return new Set(declared.filter((item): item is string => typeof item === 'string'));
  // Legacy demo manifests predate modalities. Keep their mock-only behavior.
  return new Set();
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/** Registry modality names -> dataset modality names (mirrors the backend). */
function requiredModalities(backend: BackendDef): string[] {
  return backend.input_modalities.map((item) =>
    item === 'camera_pose' || item === 'registered_pose' ? 'pose' : item);
}

/** Backend capabilities drive the UI; no backend id is special-cased here. */
function hasCapability(backend: BackendDef | undefined, name: string): boolean {
  return backend?.capabilities?.[name] === true;
}

/**
 * Whether the dataset can run this backend for this stage.
 *
 * `poseBackend` is the currently selected Pose backend: a SLAM Pose backend
 * declares the `produces_pose` capability, and the trajectory it estimates is
 * what the Surface stage consumes.
 */
export function backendCompatibility(
  ds: DatasetInfo | undefined,
  backend: BackendDef,
  stage: StageKey,
  poseBackend?: BackendDef,
): string | null {
  if (backend.status === 'disabled') return '该后端当前已禁用';
  if (!ds || ds.input_manifest?.execution !== 'real') return null;
  if (stage === 'distance') return backend.unavailable_reason || (backend.capabilities?.real_execution === true ? null : '该距离场后端仅支持模拟演示');

  const declaredPoseBackend = asString(ds.input_manifest.pose_backend);
  if (stage === 'pose') {
    if (declaredPoseBackend && declaredPoseBackend !== backend.id) {
      return `数据集注册的位姿后端为 ${declaredPoseBackend}`;
    }
    if (!declaredPoseBackend && hasCapability(backend, 'requires_pose_spec')) {
      return '数据集未注册该位姿后端所需的传感器与配置';
    }
  }
  if (stage === 'surface') {
    const registeredBackend = asString(ds.input_manifest.surface_backend);
    if (registeredBackend && backend.id !== registeredBackend) {
      return `数据集仅注册用于 ${registeredBackend}`;
    }
  }
  const available = datasetModalities(ds);
  if (stage === 'surface' && hasCapability(poseBackend, 'produces_pose')) {
    // The Pose stage of this very job estimates the trajectory Surface reads.
    available.add('pose');
  }
  const missing = requiredModalities(backend).filter((item) => !available.has(item));
  return missing.length ? `数据集缺少所需模态：${missing.join(', ')}` : null;
}

export function defaultBackendsForDataset(
  ds: DatasetInfo | undefined,
  backends: BackendsResponse,
): Record<StageKey, string | null> {
  const chosen: Record<StageKey, string | null> = { pose: null, surface: null, distance: null };
  // Pose first: its capabilities decide whether Surface can expect a pose at all.
  const poseMatch = (backends.groups.pose ?? []).find(
    (backend) => backendCompatibility(ds, backend, 'pose') === null,
  );
  chosen.pose = poseMatch?.id ?? null;
  for (const stage of ['surface', 'distance'] as StageKey[]) {
    const match = (backends.groups[stage] ?? []).find(
      (backend) => backendCompatibility(ds, backend, stage, poseMatch) === null,
    );
    chosen[stage] = match?.id ?? null;
  }
  return chosen;
}

interface UploadOutcome {
  upload: string;
  preflight: string;
  warnings: string[];
  technical: string;
}

const BACKEND_STATUS_TONES: Record<string, string> = {
  ready: 'success',
  experimental: 'warning',
  disabled: 'default',
};

const CJK_RE = /[一-鿿]/;

const MODALITY_LABELS: Record<string, string> = {
  lidar: '激光雷达',
  imu: 'IMU',
  rgb: 'RGB 图像',
  depth: '深度图',
  registered_pose: '预计算位姿',
  camera_pose: '相机位姿',
  surface_mesh: '表面网格',
};

function modalityLabel(id: string) {
  return MODALITY_LABELS[id] ?? id;
}

/** 仅把中文说明放在界面正文；英文原始描述收进可展开技术详情。 */
function hasChinese(text: string) {
  return CJK_RE.test(text);
}

function SectionTitle({
  index,
  title,
  description,
}: {
  index: string;
  title: string;
  description: string;
}) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ mb: 2 }}>
      <Box
        component="span"
        sx={{
          flex: 'none',
          width: 26,
          height: 26,
          display: 'grid',
          placeItems: 'center',
          fontSize: 14,
          fontWeight: 700,
          color: 'common.white',
          bgcolor: 'primary.main',
        }}
      >
        {index}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.35 }}>{title}</Typography>
        <Typography sx={{ fontSize: 16, color: 'text.secondary' }}>{description}</Typography>
      </Box>
    </Stack>
  );
}

function TechnicalDetails({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box
      component="details"
      onClick={(event) => event.stopPropagation()}
      sx={{ mt: 1 }}
    >
      <Box
        component="summary"
        sx={{
          cursor: 'pointer',
          fontSize: 14,
          fontWeight: 600,
          color: 'text.secondary',
          '&:hover': { color: 'text.primary' },
        }}
      >
        {label}
      </Box>
      <Box
        component="pre"
        sx={{
          mt: 1,
          mb: 0,
          p: 1.5,
          maxHeight: 240,
          overflow: 'auto',
          fontSize: 12,
          lineHeight: 1.55,
          fontFamily: 'var(--mono)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          bgcolor: 'grey.100',
          border: '1px solid',
          borderColor: 'divider',
        }}
      >
        {children}
      </Box>
    </Box>
  );
}

export function NewJobPage() {
  const [backends, setBackends] = useState<BackendsResponse | null>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[] | null>(null);
  const [selected, setSelected] = useState<Record<StageKey, string | null>>({
    pose: null,
    surface: null,
    distance: null,
  });
  const [dataset, setDataset] = useState<string>('');
  const [includeDistance, setIncludeDistance] = useState(false);
  const [runMode, setRunMode] = useState<'full' | 'short'>('full');
  const [failStage, setFailStage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [profiles, setProfiles] = useState<Array<{ id: string; name: string; version?: string; size_bytes?: number; max_size_bytes?: number; scope?: string; calibration_note: string; lidar_topic?: string; imu_topic?: string; attestation_required?: boolean; attestation_label?: string; available?: boolean; unavailable_reason?: string }>>([]);
  const [profileId, setProfileId] = useState('');
  const [sameRigConfirmed, setSameRigConfirmed] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadOutcome | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api.uploadProfiles().then((p) => { setProfiles(p); setProfileId(p[0]?.id ?? ''); }).catch((e: unknown) => setError(messageOf(e)));
    api
      .getBackends()
      .then((b) => {
        setBackends(b);
      })
      .catch((e: unknown) => setError(messageOf(e)));
    api
      .getDatasets()
      .then((d) => {
        setDatasets(d);
        const firstAvailable = d.find((item) => item.input_manifest?.available !== false);
        if (firstAvailable) {
          setDataset(firstAvailable.id);
        }
      })
      .catch((e: unknown) => setError(messageOf(e)));
  }, []);

  const selectedProfile = profiles.find((profile) => profile.id === profileId);

  const uploadBlockedReason = !selectedProfile
    ? '请选择设备配置'
    : selectedProfile.available === false
      ? '所选设备配置当前不可用'
      : selectedProfile.attestation_required && !sameRigConfirmed
        ? '请先确认设备配置声明'
        : !uploadFile
          ? '请选择 .bag 文件'
          : selectedProfile.size_bytes !== undefined
            ? uploadFile.size !== selectedProfile.size_bytes
              ? `bag 大小须与配置一致（${selectedProfile.size_bytes.toLocaleString('zh-CN')} 字节）`
              : null
            : uploadFile.size < 1 || uploadFile.size > (selectedProfile.max_size_bytes ?? 0)
              ? `bag 大小须在配置范围内（不超过 ${(selectedProfile.max_size_bytes ?? 0).toLocaleString('zh-CN')} 字节）`
              : null;

  const upload = async () => {
    if (!uploadFile || !profileId) return;
    setUploading(true);
    setError(null);
    const key = `mapping-upload:${uploadFile.name}:${uploadFile.size}:${uploadFile.lastModified}:${profileId}`;
    try {
      let id = localStorage.getItem(key);
      let state:
        | { upload_id: string; offset: number; status?: string; dataset_id?: string; max_chunk_bytes: number }
        | undefined;
      if (id) {
        state = await api.uploadStatus(id);
        if (state.status === 'rejected') { localStorage.removeItem(key); id = null; }
      }
      if (!id) {
        state = await api.createUpload(uploadFile.name, uploadFile.size, profileId, sameRigConfirmed);
        id = state.upload_id;
        localStorage.setItem(key, id);
      }
      if (!state) throw new Error('上传会话未建立');
      while (state.offset < uploadFile.size) {
        const end = Math.min(state.offset + state.max_chunk_bytes, uploadFile.size);
        let succeeded = false;
        for (let attempt = 0; attempt < 3 && !succeeded; attempt++) {
          try {
            await api.uploadChunk(id!, state.offset, uploadFile.slice(state.offset, end));
            succeeded = true;
          } catch (e) {
            state = await api.uploadStatus(id!);
            if (state.offset >= end) succeeded = true;
            else if (attempt === 2) throw e;
          }
        }
        state = await api.uploadStatus(id!);
        setUploadProgress(Math.round(state.offset * 100 / uploadFile.size));
      }
      const registered = await api.finalizeUpload(id!);
      const list = await api.getDatasets();
      setDatasets(list);
      setDataset(registered.dataset_id);
      const lidar = registered.preflight.topics[registered.lidar_topic];
      const imu = registered.preflight.topics[registered.imu_topic];
      const asUtc = (ns?: number) => ns === undefined ? '?' : new Date(Math.floor(ns / 1_000_000)).toISOString();
      setUploadResult({
        upload: registered.duplicate_of
          ? `上传完成：服务器检测到相同内容，已复用数据集 ${registered.dataset_id}。`
          : `上传完成：bag 分块上传完成，已注册数据集 ${registered.dataset_id}。`,
        preflight: `CPU 预检通过：LiDAR ${lidar?.count ?? '?'} 条，IMU ${imu?.count ?? '?'} 条。`,
        warnings: registered.preflight.warnings ?? [],
        technical: [
          `LiDAR header：${asUtc(lidar?.first_header_ns)}–${asUtc(lidar?.last_header_ns)}（UTC，毫秒精度）`,
          `IMU header：${asUtc(imu?.first_header_ns)}–${asUtc(imu?.last_header_ns)}（UTC，毫秒精度）`,
          `检查点：${registered.preflight.points_checked ?? '旧版预检仅抽样'}`,
          `无效点：${registered.preflight.invalid_points ?? '未统计'}`,
          `空帧：${registered.preflight.empty_frames ?? '未统计'}`,
          `最大逐点偏移：${registered.preflight.max_point_offset_ns ?? '未统计'} ns`,
        ].join('\n'),
      });
      localStorage.removeItem(key);
    } catch (e: unknown) {
      setError(messageOf(e));
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    if (!backends || !datasets || !dataset) return;
    setSelected(defaultBackendsForDataset(datasets.find((item) => item.id === dataset), backends));
  }, [backends, datasets, dataset]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const activeDataset = datasets?.find((item) => item.id === dataset);
      const poseBackend = backends?.groups.pose?.find((item) => item.id === selected.pose);
      const real = activeDataset?.input_manifest?.execution === 'real';
      const stages: StageKey[] = real && !includeDistance ? STAGE_ORDER.slice(0, 2) : [...STAGE_ORDER];
      const missing = stages.filter((s) => !backends?.groups[s]?.some(
        (definition) =>
          definition.id === selected[s]
          && backendCompatibility(activeDataset, definition, s, poseBackend) === null,
      ));
      if (missing.length > 0) throw new Error(`以下阶段未选择可用算法：${missing.map((stage) => STAGE_NAMES[stage]).join('、')}`);
      const body = {
        dataset,
        ...(Array.isArray(activeDataset?.input_manifest?.run_modes) ? { run_mode: runMode } : {}),
        backends: Object.fromEntries(
          stages.map((s) => [s, selected[s]!]),
        ) as Record<string, string>,
        fail_stage: real ? null : failStage || null,
        requested_stages: stages,
      };
      const job = await api.createJob(body);
      if (real && stages.length === 2) await api.runPlanned(job.job_id);
      else await api.runAll(job.job_id);
      navigate(`/jobs/${job.job_id}`);
    } catch (e: unknown) {
      setError(messageOf(e));
      setSubmitting(false);
    }
  };

  const formatInput = (ds: DatasetInfo) => {
    const m = ds.input_manifest as Record<string, unknown> | undefined;
    if (!m) return '';
    const parts = Object.entries(m).map(([k, v]) => `${k}=${JSON.stringify(v)}`);
    return parts.join(' · ');
  };

  const activeDataset = datasets?.find((item) => item.id === dataset);
  const real = activeDataset?.input_manifest?.execution === 'real';
  const requiredStages: StageKey[] = real && !includeDistance ? STAGE_ORDER.slice(0, 2) : [...STAGE_ORDER];
  const hasRunModes = Array.isArray(activeDataset?.input_manifest?.run_modes);

  return (
    <Box>
      <Box sx={{ mb: 2.5 }}>
        <Typography component="h1" sx={{ fontSize: 32, fontWeight: 700, lineHeight: 1.2 }}>
          新建任务
        </Typography>
        <Typography sx={{ mt: 0.5, fontSize: 16, color: 'text.secondary' }}>
          上传数据、选择设备配置与各阶段算法，然后创建三维建图任务。
        </Typography>
      </Box>

      {error ? (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}

      {!backends || !datasets ? (
        <Stack alignItems="center" spacing={2} sx={{ py: 12, color: 'text.secondary' }}>
          <CircularProgress size={28} />
          <Typography sx={{ fontSize: 16 }}>加载算法与数据集配置…</Typography>
        </Stack>
      ) : (
        <Stack spacing={2}>
          <Card sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
            <SectionTitle
              index="①"
              title="数据与设备"
              description="上传 ROS1 bag v2 的 INS / Livox 数据，或选择已注册数据集。"
            />

            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1.2fr) minmax(0, 1fr)' },
                gap: 2,
              }}
            >
              <Box>
                <Typography sx={{ mb: 1, fontSize: 16, fontWeight: 700 }}>上传 bag 并注册数据集</Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }}>
                  <Button
                    component="label"
                    variant="outlined"
                    startIcon={<CloudUploadRoundedIcon />}
                    disabled={uploading}
                    sx={{ justifyContent: 'flex-start', whiteSpace: 'nowrap' }}
                  >
                    {uploadFile ? '更换 bag 文件' : '选择 .bag 文件'}
                    <input
                      type="file"
                      accept=".bag"
                      hidden
                      onChange={(event) => {
                        setUploadFile(event.target.files?.[0] ?? null);
                        setUploadProgress(0);
                        setUploadResult(null);
                      }}
                    />
                  </Button>
                  <Typography
                    sx={{
                      minWidth: 0,
                      fontSize: 14,
                      color: uploadFile ? 'text.primary' : 'text.secondary',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={uploadFile?.name}
                  >
                    {uploadFile ? `${uploadFile.name}（${uploadFile.size.toLocaleString('zh-CN')} 字节）` : '尚未选择文件'}
                  </Typography>
                </Stack>

                <FormControl fullWidth size="small" sx={{ mt: 1.5 }}>
                  <Select
                    value={profileId}
                    displayEmpty
                    inputProps={{ 'aria-label': '设备配置' }}
                    onChange={(event) => {
                      setProfileId(event.target.value);
                      setSameRigConfirmed(false);
                      setUploadResult(null);
                      setUploadProgress(0);
                    }}
                  >
                    {profiles.length === 0 ? (
                      <MenuItem value="" disabled>
                        暂无设备配置
                      </MenuItem>
                    ) : null}
                    {profiles.map((profile) => (
                      <MenuItem key={profile.id} value={profile.id} disabled={profile.available === false}>
                        {profile.name}
                        {profile.version ? ` v${profile.version}` : ''}
                        {profile.available === false ? '（配置不可用）' : ''}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                {selectedProfile ? (
                  <Stack spacing={0.75} sx={{ mt: 1 }}>
                    {selectedProfile.scope ? (
                      <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
                        适用范围：{selectedProfile.scope}
                      </Typography>
                    ) : null}
                    <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
                      {selectedProfile.calibration_note}
                    </Typography>
                    <Typography sx={{ fontSize: 12, color: 'text.disabled' }}>
                      大小限制：
                      {selectedProfile.size_bytes !== undefined
                        ? `须恰好 ${selectedProfile.size_bytes.toLocaleString('zh-CN')} 字节`
                        : `不超过 ${(selectedProfile.max_size_bytes ?? 0).toLocaleString('zh-CN')} 字节`}
                      {selectedProfile.lidar_topic ? ` · LiDAR ${selectedProfile.lidar_topic}` : ''}
                      {selectedProfile.imu_topic ? ` · IMU ${selectedProfile.imu_topic}` : ''}
                    </Typography>
                    {selectedProfile.available === false ? (
                      <>
                        <Alert severity="error" title={selectedProfile.unavailable_reason}>
                          该设备配置当前不可用，请展开原始原因查看详情
                        </Alert>
                        {selectedProfile.unavailable_reason ? (
                          <TechnicalDetails label="不可用原因（原始字段）">
                            {selectedProfile.unavailable_reason}
                          </TechnicalDetails>
                        ) : null}
                      </>
                    ) : null}
                    {selectedProfile.attestation_required ? (
                      <FormControlLabel
                        control={
                          <Checkbox
                            size="small"
                            checked={sameRigConfirmed}
                            onChange={(event) => setSameRigConfirmed(event.target.checked)}
                          />
                        }
                        label={
                          <Typography sx={{ fontSize: 14 }}>
                            {selectedProfile.attestation_label || '我确认本次数据与所选设备配置为同一套设备'}
                          </Typography>
                        }
                        sx={{ alignItems: 'flex-start', mt: 0.5 }}
                      />
                    ) : null}
                  </Stack>
                ) : null}

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }} sx={{ mt: 1.5 }}>
                  <Button
                    variant="contained"
                    startIcon={<CloudUploadRoundedIcon />}
                    disabled={uploadBlockedReason !== null || uploading}
                    onClick={() => void upload()}
                  >
                    {uploading ? `上传与预检中 ${uploadProgress}%` : '上传、预检并注册数据集'}
                  </Button>
                  {uploadBlockedReason ? (
                    <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>{uploadBlockedReason}</Typography>
                  ) : null}
                </Stack>

                {uploading ? (
                  <Box sx={{ mt: 1.5 }}>
                    <LinearProgress variant="determinate" value={uploadProgress} sx={{ height: 8 }} />
                    <Typography sx={{ mt: 0.5, fontSize: 12, color: 'text.secondary' }}>
                      分块上传中，可中断后继续；完成后自动进入 CPU 预检与数据集注册。
                    </Typography>
                  </Box>
                ) : null}

                {uploadResult ? (
                  <Stack spacing={1} sx={{ mt: 1.5 }}>
                    <Alert severity="success">{uploadResult.upload}</Alert>
                    <Alert severity="success">
                      {uploadResult.preflight}
                      {uploadResult.warnings.length > 0 ? (
                        <Box component="ul" sx={{ m: 0, pl: 2.25 }}>
                          {uploadResult.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </Box>
                      ) : null}
                    </Alert>
                    <Alert severity="info">
                      预检仅确认结构与所选配置的运行条件，不代表算法成功或精度合格。
                    </Alert>
                    <TechnicalDetails label="预检原始读数">{uploadResult.technical}</TechnicalDetails>
                  </Stack>
                ) : null}
              </Box>

              <Box>
                <Typography sx={{ mb: 1, fontSize: 16, fontWeight: 700 }}>已注册数据集</Typography>
                {datasets.length === 0 ? (
                  <Box
                    sx={{
                      p: 2,
                      fontSize: 14,
                      color: 'text.secondary',
                      border: '1px dashed',
                      borderColor: 'divider',
                    }}
                  >
                    暂无可选数据集，请先上传 bag 并完成注册。
                  </Box>
                ) : null}
                <Stack spacing={1}>
                  {datasets.map((ds) => {
                    const unavailable = ds.input_manifest?.available === false;
                    const active = ds.id === dataset;
                    return (
                      <Box
                        key={ds.id}
                        component="label"
                        sx={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 1,
                          p: 1.25,
                          cursor: unavailable ? 'not-allowed' : 'pointer',
                          opacity: unavailable ? 0.68 : 1,
                          bgcolor: active ? 'primary.lighter' : 'background.paper',
                          border: '1px solid',
                          borderColor: active ? 'primary.main' : 'divider',
                          '&:hover': { borderColor: active ? 'primary.main' : 'grey.400' },
                        }}
                      >
                        <Radio
                          size="small"
                          name="dataset"
                          value={ds.id}
                          checked={active}
                          disabled={unavailable}
                          onChange={() => setDataset(ds.id)}
                          sx={{ p: 0.5, mt: -0.25 }}
                        />
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap">
                            <Typography sx={{ fontSize: 15, fontWeight: 700 }}>{ds.name}</Typography>
                            <Box component="code" sx={{ fontSize: 12, color: 'text.secondary', wordBreak: 'break-all' }}>
                              {ds.id}
                            </Box>
                          </Stack>
                          {ds.description && hasChinese(ds.description) ? (
                            <Typography sx={{ mt: 0.25, fontSize: 13, color: 'text.secondary' }}>
                              {ds.description}
                            </Typography>
                          ) : null}
                          {ds.input_manifest?.execution === 'mock' ? (
                            <Typography sx={{ mt: 0.5, fontSize: 13, color: 'primary.dark', fontWeight: 600 }}>
                              演示任务 · 合成数据 · 后台每阶段约30秒
                            </Typography>
                          ) : null}
                          {unavailable ? (
                            <Alert
                              severity="error"
                              sx={{ mt: 0.75, py: 0.25 }}
                              title={String(ds.input_manifest?.availability_message || '')}
                            >
                              服务器数据不可用，请展开技术清单查看原始原因
                            </Alert>
                          ) : null}
                          {ds.input_manifest ? (
                            <TechnicalDetails label="技术清单（原始字段）">
                              {ds.description ? `description=${JSON.stringify(ds.description)} · ` : ''}
                              {formatInput(ds)}
                            </TechnicalDetails>
                          ) : null}
                        </Box>
                      </Box>
                    );
                  })}
                </Stack>
              </Box>
            </Box>

            {dataset && !selected.surface ? (
              <Alert severity="error" sx={{ mt: 2 }}>
                所选数据集当前没有兼容且可运行的表面重建算法。
              </Alert>
            ) : null}
          </Card>

          <Card sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
            <SectionTitle
              index="②"
              title="阶段算法"
              description={
                real
                  ? '默认运行 Pose→Surface；可显式选择三阶段。第三模块须先通过依赖与契约检查。'
                  : '演示数据包含位姿估计、表面重建与距离场三个模拟阶段。'
              }
            />

            {real ? <Stack spacing={1} sx={{ mb: 2 }}>
              <Typography>运行阶段</Typography>
              <Select size="small" value={includeDistance ? 'three' : 'two'}
                onChange={(event) => setIncludeDistance(event.target.value === 'three')}>
                <MenuItem value="two">Pose → Surface（默认）</MenuItem>
                <MenuItem value="three">Pose → Surface → Distance</MenuItem>
              </Select>
              <Alert severity="info">{backends.groups.distance.find((item) => item.id === 'voxel_esdf')?.unavailable_reason || '真实距离场可运行；仅在有效观测支持域计算，未知区域保留。完整三阶段结果以本任务验收为准。'}</Alert>
            </Stack> : null}
            <Stack spacing={2}>
              {requiredStages.map((stage) => {
                const definitions = backends.groups[stage] ?? [];
                const selectedPoseBackend = backends.groups.pose?.find((item) => item.id === selected.pose);
                return (
                  <Box key={stage}>
                    <Typography sx={{ mb: 1, fontSize: 16, fontWeight: 700 }}>
                      {STAGE_NAMES[stage]}
                    </Typography>
                    {definitions.length === 0 ? (
                      <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
                        该阶段暂无可用算法。
                      </Typography>
                    ) : (
                      <Box
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'repeat(2, minmax(0, 1fr))' },
                          gap: 1,
                        }}
                      >
                        {definitions.map((backend) => {
                          const incompatibility = backendCompatibility(activeDataset, backend, stage, selectedPoseBackend);
                          const disabled = incompatibility !== null;
                          const active = selected[stage] === backend.id;
                          const tone = BACKEND_STATUS_TONES[backend.status] ?? 'default';
                          return (
                            <Box
                              key={backend.id}
                              component="label"
                              title={incompatibility ?? undefined}
                              sx={{
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: 1,
                                p: 1.25,
                                cursor: disabled ? 'not-allowed' : 'pointer',
                                opacity: disabled ? 0.72 : 1,
                                bgcolor: active ? 'primary.lighter' : 'background.paper',
                                border: '1px solid',
                                borderColor: active ? 'primary.main' : 'divider',
                                '&:hover': { borderColor: active ? 'primary.main' : 'grey.400' },
                              }}
                            >
                              <Radio
                                size="small"
                                name={`backend-${stage}`}
                                value={backend.id}
                                checked={active}
                                disabled={disabled}
                                onChange={() => setSelected((prev) => ({ ...prev, [stage]: backend.id }))}
                                sx={{ p: 0.5, mt: -0.25 }}
                              />
                              <Box sx={{ minWidth: 0, flex: 1 }}>
                                <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap">
                                  <Typography sx={{ fontSize: 15, fontWeight: 700 }}>
                                    {backend.display_name}
                                  </Typography>
                                  <Box
                                    component="span"
                                    sx={{
                                      px: 0.75,
                                      py: 0.1,
                                      fontSize: 11,
                                      fontWeight: 600,
                                      color: tone === 'default' ? 'text.secondary' : `${tone}.dark`,
                                      bgcolor: tone === 'default' ? 'grey.100' : `${tone}.lighter`,
                                      border: '1px solid',
                                      borderColor: tone === 'default' ? 'divider' : `${tone}.main`,
                                    }}
                                  >
                                    {BACKEND_STATUS_LABELS[backend.status] ?? backend.status}
                                  </Box>
                                </Stack>
                                <Typography sx={{ mt: 0.25, fontSize: 11, color: 'text.disabled', wordBreak: 'break-all' }}>
                                  输入：{backend.input_modalities.map(modalityLabel).join(' / ') || '—'}
                                </Typography>
                                {incompatibility ? (
                                  <Alert severity="error" sx={{ mt: 0.75, py: 0.25 }}>
                                    {incompatibility}
                                  </Alert>
                                ) : null}
                                <TechnicalDetails label="能力与原始信息">
                                  {JSON.stringify(
                                    {
                                      id: backend.id,
                                      status: backend.status,
                                      description: backend.description,
                                      unavailable_reason: backend.unavailable_reason,
                                      input_modalities: backend.input_modalities,
                                      capabilities: backend.capabilities,
                                      home_url: backend.home_url,
                                    },
                                    null,
                                    2,
                                  )}
                                </TechnicalDetails>
                              </Box>
                            </Box>
                          );
                        })}
                      </Box>
                    )}
                  </Box>
                );
              })}
            </Stack>
          </Card>

          <Card sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
            <SectionTitle
              index="③"
              title="运行范围"
              description={
                real
                  ? (includeDistance ? '自动运行完整位姿估计、表面重建和同任务距离场转换。' : '创建真实任务后自动运行位姿估计，再交给完整表面重建。')
                  : '演示任务可指定模拟失败的阶段，用于验证失败、取消与重跑流程。'
              }
            />

            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'repeat(2, minmax(0, 1fr))' },
                gap: 2,
              }}
            >
              {hasRunModes ? (
                <Box>
                  <Typography sx={{ mb: 0.75, fontSize: 16, fontWeight: 700 }}>范围模式</Typography>
                  <FormControl fullWidth size="small">
                    <Select
                      value={runMode}
                      inputProps={{ 'aria-label': '运行范围' }}
                      onChange={(event) => setRunMode(event.target.value as 'full' | 'short')}
                    >
                      <MenuItem value="full">完整运行</MenuItem>
                      <MenuItem value="short">短段验证</MenuItem>
                    </Select>
                  </FormControl>
                  <Typography sx={{ mt: 0.75, fontSize: 14, color: 'text.secondary' }}>
                    {runMode === 'full'
                      ? '完整运行：位姿估计处理完整序列，表面重建处理全部可用帧，不限制前 100 帧。'
                      : '短段验证：位姿估计处理完整序列，表面重建仅处理原始第 1–100 帧，沿用已验证策略。'}
                  </Typography>
                </Box>
              ) : null}

              {!real ? (
                <Box>
                  <Typography sx={{ mb: 0.75, fontSize: 16, fontWeight: 700 }}>演示失败选项</Typography>
                  <FormControl fullWidth size="small">
                    <Select
                      value={failStage}
                      inputProps={{ 'aria-label': '模拟失败阶段' }}
                      onChange={(event) => setFailStage(event.target.value)}
                    >
                      <MenuItem value="">不模拟失败（全部成功）</MenuItem>
                      <MenuItem value="pose">{STAGE_NAMES.pose}阶段失败</MenuItem>
                      <MenuItem value="surface">{STAGE_NAMES.surface}阶段失败</MenuItem>
                      <MenuItem value="distance">{STAGE_NAMES.distance}阶段失败</MenuItem>
                    </Select>
                  </FormControl>
                  <Typography sx={{ mt: 0.75, fontSize: 14, color: 'text.secondary' }}>
                    仅模拟运行器（Mock Runner）使用，用于演示阶段失败、取消与重跑；真实算法接入后自动忽略。
                  </Typography>
                </Box>
              ) : null}
            </Box>

            <Divider sx={{ my: 1.5 }} />

            <TechnicalDetails label="技术说明与验收边界">
              {[
                '位姿时间关联门限保持 98%。',
                '原 INS 验收仅适用于已验证样本；自采设备须独立核对标定，原 INS 外参及 IMU 单位依据待确认。',
                real
                  ? '本次两阶段任务不运行距离场，不验收建图精度。'
                  : '演示任务使用模拟运行器（Mock Runner），结果仅用于验证交互流程，不代表真实精度。',
                `将创建阶段：${requiredStages.map((stage) => STAGE_NAMES[stage]).join(' → ')}。`,
              ].join('\n')}
            </TechnicalDetails>
          </Card>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }}>
            <Button
              variant="contained"
              size="large"
              startIcon={<RocketLaunchRoundedIcon />}
              onClick={() => void submit()}
              disabled={submitting || requiredStages.some((stage) => !selected[stage])}
            >
              {submitting ? '创建中…' : '创建并一键运行'}
            </Button>
            <Button variant="text" onClick={() => navigate('/')} disabled={submitting}>
              取消
            </Button>
            <Box sx={{ flex: 1 }} />
            <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
              将创建：{requiredStages.map((stage) => STAGE_NAMES[stage]).join(' → ')}
              {real ? '（自动运行）' : '（演示）'}
            </Typography>
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
