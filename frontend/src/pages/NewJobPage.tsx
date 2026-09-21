import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, messageOf } from '../api/api';
import type { BackendDef, BackendsResponse, DatasetInfo, StageKey } from '../types';
import { BACKEND_STATUS_LABELS } from '../components/PipelineView';

const STAGE_ORDER: StageKey[] = ['pose', 'surface', 'distance'];

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
        // 默认预选每个阶段第一个"可用"算法（ready/experimental）。
        const pre: Record<StageKey, string | null> = { pose: null, surface: null, distance: null };
        for (const s of STAGE_ORDER) {
          const defs = b.groups[s] ?? [];
          const pick = defs.find((d) => d.status !== 'disabled');
          pre[s] = pick?.id ?? null;
        }
        setSelected(pre);
      })
      .catch((e: unknown) => setError(messageOf(e)));
    api
      .getDatasets()
      .then((d) => {
        setDatasets(d);
        if (d.length > 0) setDataset(d[0].id);
      })
      .catch((e: unknown) => setError(messageOf(e)));
  }, []);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const missing = STAGE_ORDER.filter((s) => !backends?.groups[s]?.some((d) => d.id === selected[s]));
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
                <label key={ds.id} className={`dataset-card ${ds.id === dataset ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="dataset"
                    value={ds.id}
                    checked={ds.id === dataset}
                    onChange={() => setDataset(ds.id)}
                  />
                  <div>
                    <div className="dataset-name">
                      {ds.name} <code>{ds.id}</code>
                    </div>
                    <div className="dataset-desc">{ds.description}</div>
                    {ds.input_manifest ? <div className="dataset-manifest">{formatInput(ds)}</div> : null}
                  </div>
                </label>
              ))}
            </div>
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
                    const disabled = b.status === 'disabled';
                    return (
                      <label
                        key={b.id}
                        className={`backend-card ${selected[s] === b.id ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
                        title={b.description}
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
            <button className="btn btn-primary btn-lg" onClick={() => void submit()} disabled={submitting}>
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