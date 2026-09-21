import type { ArtifactInfo, Manifest } from '../types';
import { api } from '../api/api';

export interface ArtifactsPanelProps {
  jobId: string;
  stage: string;
  manifest: Manifest | null;
}

/**
 * 产物面板：完全由 manifest 驱动。
 * - artifact_id → 后端地址，绝不接收任意路径（架构约束：防 Path Traversal）。
 * - 仅当 download === true 才显示下载链接；否则只读展示。
 */
export function ArtifactsPanel({ jobId, stage, manifest }: ArtifactsPanelProps) {
  if (!manifest) return <div className="panel-empty">阶段尚未生成产物 manifest。</div>;

  const { artifacts, metrics, backend_details } = manifest;

  return (
    <div className="artifacts">
      <div className="artifacts-head">
        <span>产物清单</span>
        <span className="muted">
          {manifest.backend} · schema {manifest.schema_version}
        </span>
      </div>

      {metrics ? (
        <div className="metrics">
          {Object.entries(metrics).map(([k, v]) => (
            <div className="metric" key={k}>
              <span className="metric-key">{k}</span>
              <MetricValue v={v} />
            </div>
          ))}
        </div>
      ) : null}

      <div className="artifact-list">
        {artifacts.length === 0 ? <div className="panel-empty">（manifest 无产物）</div> : null}
        {artifacts.map((a: ArtifactInfo) => (
          <div className="artifact-row" key={a.artifact_id}>
            <span className={`role-tag role-${a.role}`}>{a.role === 'preview' ? '预览' : '数据'}</span>
            <code className="artifact-id">{a.artifact_id}</code>
            <span className="artifact-ctype">{a.content_type.split('/')[1] ?? a.content_type}</span>
            {a.download === true ? (
              <a
                className="btn btn-download"
                href={api.artifactUrl(jobId, stage, a.artifact_id)}
                download={`${a.artifact_id}.${ext(a.content_type)}`}
                title={a.path}
              >
                ⬇ 下载
              </a>
            ) : (
              <span className="no-download" title={a.path}>
                {a.role === 'preview' ? '仅预览' : '不可下载'}
              </span>
            )}
          </div>
        ))}
      </div>

      {backend_details ? (
        <div className="backend-details">
          <div className="backend-details-title">算法细节</div>
          <pre className="backend-details-pre">{JSON.stringify(backend_details, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function MetricValue({ v }: { v: unknown }) {
  if (Array.isArray(v)) {
    return (
      <span className="metric-key-tags">
        {v.map((x) => (
          <span className="tag" key={String(x)}>
            {String(x)}
          </span>
        ))}
      </span>
    );
  }
  return <span className="metric-val">{String(v)}</span>;
}

function ext(contentType: string): string {
  const t = contentType.split('/')[1] ?? 'bin';
  if (t === 'json') return 'json';
  if (t === 'gltf-binary') return 'glb';
  if (t.startsWith('png')) return 'png';
  if (t === 'octet-stream') return 'bin';
  return t.replace(/[^a-z0-9]/gi, '_');
}