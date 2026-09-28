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

export function backendCompatibility(ds: DatasetInfo | undefined, backend: BackendDef, stage: StageKey): string | null {
  if (backend.status === 'disabled') return backend.unavailable_reason || '该后端当前不可用';
  if (!ds || ds.input_manifest?.execution !== 'real') return null;
  if (stage === 'pose' && backend.id !== 'registered_pose_import') return '真实注册数据集仅支持 registered_pose_import';
  if (stage !== 'surface') return null;
  const registeredBackend = ds.input_manifest.surface_backend;
  if (typeof registeredBackend === 'string' && registeredBackend && backend.id !== registeredBackend) {
    return `数据集仅注册用于 ${registeredBackend}`;
  }
  const available = datasetModalities(ds);
  const required = backend.input_modalities.map((item) => item === 'camera_pose' ? 'pose' : item);
  const missing = required.filter((item) => !available.has(item));
  return missing.length ? `数据集缺少所需模态：${missing.join(', ')}` : null;
}

export function defaultBackendsForDataset(
  ds: DatasetInfo | undefined,
  backends: BackendsResponse,
): Record<StageKey, string | null> {
  return Object.fromEntries(STAGE_ORDER.map((stage) => {
    const match = (backends.groups[stage] ?? []).find(
      (backend) => backendCompatibility(ds, backend, stage) === null,
    );
    return [stage, match?.id ?? null];
  })) as Record<StageKey, string | null>;
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
  const [failStage, setFailStage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
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

  useEffect(() => {
    if (!backends || !datasets || !dataset) return;
    setSelected(defaultBackendsForDataset(datasets.find((item) => item.id === dataset), backends));
  }, [backends, datasets, dataset]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const activeDataset = datasets?.find((item) => item.id === dataset);
      const missing = STAGE_ORDER.filter((s) => !backends?.groups[s]?.some(
        (definition) => definition.id === selected[s] && backendCompatibility(activeDataset, definition, s) === null,
      ));
      if (missing.length > 0) throw new Error(`以下阶段未选择可用算法：${missing.join(', ')}`);
      const body = {
        dataset,
        backends: Object.fromEntries(
          STAGE_ORDER.map((s) => [s, selected[s]!]),
        ) as Record<string, string>,
        fail_stage: failStage || null,
      };
      const job = await api.createJob(body);
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
              阶段固定为 Pose / Surface / Distance 三步串行；三种算法的最终导出格式一致，
              只需替换后端 adapter，前端与产物结构无需改动。
            </p>
            {STAGE_ORDER.map((s) => (
              <div className="backend-group" key={s}>
                <div className="backend-group-label">
                  {s === 'pose' ? 'Pose / SLAM' : s === 'surface' ? 'Surface Mapping' : 'Distance / ESDF'}
                </div>
                <div className="backend-grid">
                  {backends.groups[s].map((b: BackendDef) => {
                    const activeDataset = datasets.find((d) => d.id === dataset);
                    const incompatibility = backendCompatibility(activeDataset, b, s);
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

          <section className="form-section">
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
          </section>

          <div className="form-actions">
            <button className="btn btn-primary btn-lg" onClick={() => void submit()} disabled={submitting || STAGE_ORDER.some((stage) => !selected[stage])}>
              {submitting ? '创建中…' : '🚀 创建任务'}
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
