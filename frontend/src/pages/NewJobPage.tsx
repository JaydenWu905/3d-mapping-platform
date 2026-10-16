import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, messageOf } from '../api/api';
import type { BackendDef, BackendsResponse, DatasetInfo, StageKey } from '../types';
import { BACKEND_STATUS_LABELS } from '../components/PipelineView';

const STAGE_ORDER: StageKey[] = ['pose', 'surface', 'distance'];

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
  if (backend.status === 'disabled') return backend.unavailable_reason || '该后端当前不可用';
  if (!ds || ds.input_manifest?.execution !== 'real') return null;
  // Distance has no real runner yet; the backend reports that with its own
  // message when the chain reaches it, so selection stays permissive here.
  if (stage === 'distance') return null;

  const declaredPoseBackend = asString(ds.input_manifest.pose_backend);
  if (stage === 'pose') {
    if (declaredPoseBackend && declaredPoseBackend !== backend.id) {
      return `数据集注册的 Pose 后端为 ${declaredPoseBackend}`;
    }
    if (!declaredPoseBackend && hasCapability(backend, 'requires_pose_spec')) {
      return '数据集未注册该 Pose 后端所需的传感器与配置';
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

export function NewJobPage() {
  const [backends, setBackends] = useState<BackendsResponse | null>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[] | null>(null);
  const [selected, setSelected] = useState<Record<StageKey, string | null>>({
    pose: null,
    surface: null,
    distance: null,
  });
  const [dataset, setDataset] = useState<string>('');
  const [runMode, setRunMode] = useState<'full' | 'short'>('full');
  const [failStage, setFailStage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [profiles, setProfiles] = useState<Array<{ id: string; name: string; size_bytes?: number; max_size_bytes?: number; scope?: string; calibration_note: string }>>([]);
  const [profileId, setProfileId] = useState('');
  const [sameRigConfirmed, setSameRigConfirmed] = useState(false);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
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

  const upload = async () => {
    if (!uploadFile || !profileId) return;
    setUploading(true);
    setError(null);
    const key = `mapping-upload:${uploadFile.name}:${uploadFile.size}:${uploadFile.lastModified}:${profileId}`;
    try {
      let id = localStorage.getItem(key);
      let state;
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
      const lidar = registered.preflight.topics['/livox_mid360/livox/lidar'];
      const imu = registered.preflight.topics['/livox_mid360/livox/imu'];
      const asUtc = (ns?: number) => ns === undefined ? '?' : new Date(Math.floor(ns / 1_000_000)).toISOString();
      setUploadResult(`${registered.duplicate_of ? '重复内容，已复用数据集' : 'CPU 预检通过，已注册数据集'} ${registered.dataset_id}。LiDAR ${lidar?.count ?? '?'} 条，IMU ${imu?.count ?? '?'} 条；LiDAR header ${asUtc(lidar?.first_header_ns)}–${asUtc(lidar?.last_header_ns)}，IMU header ${asUtc(imu?.first_header_ns)}–${asUtc(imu?.last_header_ns)}（UTC，毫秒精度）；检查点 ${registered.preflight.points_checked ?? '旧版预检仅抽样'}，无效点 ${registered.preflight.invalid_points ?? '未统计'}，空帧 ${registered.preflight.empty_frames ?? '未统计'}，最大逐点偏移 ${registered.preflight.max_point_offset_ns ?? '未统计'} ns。${registered.preflight.warnings?.join('；') ?? ''}`);
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
      const stages = real ? STAGE_ORDER.slice(0, 2) : STAGE_ORDER;
      const missing = stages.filter((s) => !backends?.groups[s]?.some(
        (definition) =>
          definition.id === selected[s]
          && backendCompatibility(activeDataset, definition, s, poseBackend) === null,
      ));
      if (missing.length > 0) throw new Error(`以下阶段未选择可用算法：${missing.join(', ')}`);
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
      if (real) await api.runPlanned(job.job_id);
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

  return (
    <div className="page">
      <div className="page-head">
        <h2>新建建图任务</h2>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {!backends || !datasets ? (
        <div className="panel-empty">加载算法与数据集配置…</div>
      ) : (
        <div className="new-job">
          <section className="form-section">
            <h3>① 选择数据集</h3>
            <div className="field">
              <span className="field-label">上传 ROS1 bag v2 的 INS/Livox 数据</span>
              <input type="file" accept=".bag" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} />
              <select value={profileId} onChange={(e) => { setProfileId(e.target.value); setSameRigConfirmed(false); setUploadResult(null); }}>{profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
              <span className="field-hint">{profiles.find((p) => p.id === profileId)?.scope} {profiles.find((p) => p.id === profileId)?.calibration_note}</span>
              {profileId === 'ins_livox_mid360_same_rig' ? <label><input type="checkbox" checked={sameRigConfirmed} onChange={(e) => setSameRigConfirmed(e.target.checked)} /> 我确认这是同一物理设备、安装和采集配置；标定仍待来源确认。</label> : null}
              <button className="btn btn-primary" disabled={!uploadFile || uploading || !profileId || (profileId === 'ins_livox_mid360_same_rig' && !sameRigConfirmed) || (profiles.find((p) => p.id === profileId)?.size_bytes !== undefined ? uploadFile.size !== profiles.find((p) => p.id === profileId)?.size_bytes : uploadFile.size < 1 || uploadFile.size > (profiles.find((p) => p.id === profileId)?.max_size_bytes ?? 0))} onClick={() => void upload()}>{uploading ? `上传与预检中 ${uploadProgress}%` : '上传、预检并自动注册'}</button>
              {uploadResult ? <div className="field-hint">{uploadResult} 预检仅确认结构与所选配置的运行条件，不代表算法成功或精度合格。</div> : null}
            </div>
            <div className="dataset-list">
              {datasets.map((ds) => (
                <label key={ds.id} className={`dataset-card ${ds.id === dataset ? 'selected' : ''} ${ds.input_manifest?.available === false ? 'disabled' : ''}`}>
                  <input
                    type="radio"
                    name="dataset"
                    value={ds.id}
                    checked={ds.id === dataset}
                    disabled={ds.input_manifest?.available === false}
                    onChange={() => {
                      setDataset(ds.id);
                    }}
                  />
                  <div>
                    <div className="dataset-name">
                      {ds.name} <code>{ds.id}</code>
                    </div>
                    <div className="dataset-desc">{ds.description}</div>
                    {ds.input_manifest?.available === false ? (
                      <div className="alert alert-error">{String(ds.input_manifest.availability_message || '服务器数据不可用')}</div>
                    ) : null}
                    {ds.input_manifest ? <div className="dataset-manifest">{formatInput(ds)}</div> : null}
                  </div>
                </label>
              ))}
            </div>
            {dataset && !selected.surface ? (
              <div className="alert alert-error">所选数据集当前没有兼容且可运行的 Surface backend。</div>
            ) : null}
          </section>

          <section className="form-section">
            <h3>② 为每个阶段选择算法</h3>
            <p className="form-tip">
              真实数据执行 Pose / Surface 两阶段；Distance 未接入。演示数据保留三阶段。
            </p>
            {(datasets.find((d) => d.id === dataset)?.input_manifest?.execution === 'real' ? STAGE_ORDER.slice(0, 2) : STAGE_ORDER).map((s) => (
              <div className="backend-group" key={s}>
                <div className="backend-group-label">
                  {s === 'pose' ? 'Pose / SLAM' : s === 'surface' ? 'Surface Mapping' : 'Distance / ESDF'}
                </div>
                <div className="backend-grid">
                  {backends.groups[s].map((b: BackendDef) => {
                    const activeDataset = datasets.find((d) => d.id === dataset);
                    const selectedPoseBackend = backends.groups.pose.find(
                      (item) => item.id === selected.pose,
                    );
                    const incompatibility = backendCompatibility(activeDataset, b, s, selectedPoseBackend);
                    const disabled = incompatibility !== null;
                    return (
                      <label
                        key={b.id}
                        className={`backend-card ${selected[s] === b.id ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
                        title={incompatibility || b.description}
                      >
                        <input
                          type="radio"
                          name={`backend-${s}`}
                          value={b.id}
                          disabled={disabled}
                          checked={selected[s] === b.id}
                          onChange={() => setSelected((prev) => ({ ...prev, [s]: b.id }))}
                        />
                        <div className="backend-name">{b.display_name}</div>
                        <div className="backend-meta">
                          <span className={`pill pill-${b.status}`}>{BACKEND_STATUS_LABELS[b.status]}</span>
                          <span className="backend-modalities">{b.input_modalities.join('/') || '—'}</span>
                        </div>
                        <div className="backend-desc">{b.description}</div>
                        {incompatibility ? <div className="alert alert-error">{incompatibility}</div> : null}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </section>

          {Array.isArray(datasets.find(d => d.id === dataset)?.input_manifest?.run_modes) ? <section className="form-section">
            <h3>③ 运行范围</h3>
            <label className="field"><span className="field-label">范围模式</span>
              <select aria-label="运行范围" value={runMode} onChange={e => setRunMode(e.target.value as 'full' | 'short')}>
                <option value="full">完整运行</option><option value="short">短段验证</option>
              </select>
            </label>
            <p>{runMode === 'full' ? '完整运行：新运行 GLIM 处理完整序列，再自动将本 Job 的新轨迹交给完整 Surface；不限制前 100 帧。' : '短段验证：新运行 GLIM 处理完整序列，Surface 仅处理原始第 1–100 帧，沿用已验证策略。'}</p>
            <p>Pose 时间关联门限保持 98%。仅适用于已验证 INS profile；外参及 IMU 单位依据待确认。Distance 未接入，本轮不验收建图精度。</p>
          </section> : null}
          {datasets.find(d => d.id === dataset)?.input_manifest?.execution !== 'real' ? <section className="form-section">
            <h3>③ 演示选项（仅 Mock Runner）</h3>
            <label className="field">
              <span className="field-label">在哪个阶段模拟失败？</span>
              <select value={failStage} onChange={(e) => setFailStage(e.target.value)}>
                <option value="">不模拟失败（全部成功）</option>
                <option value="pose">Pose 阶段失败</option>
                <option value="surface">Surface 阶段失败</option>
                <option value="distance">Distance 阶段失败</option>
              </select>
              <span className="field-hint">用于演示阶段失败 / 取消 / 重跑流程；真实算法接入后自动忽略。</span>
            </label>
          </section> : null}

          <div className="form-actions">
            <button className="btn btn-primary btn-lg" onClick={() => void submit()} disabled={submitting || (datasets.find((d) => d.id === dataset)?.input_manifest?.execution === 'real' ? STAGE_ORDER.slice(0, 2) : STAGE_ORDER).some((stage) => !selected[stage])}>
              {submitting ? '创建中…' : datasets.find((d) => d.id === dataset)?.input_manifest?.execution === 'real' ? '🚀 创建并一键运行' : '🚀 创建任务'}
            </button>
            <button className="btn btn-ghost" onClick={() => navigate('/')} disabled={submitting}>
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
