import type { Manifest } from '../types';
import { api } from '../api/api';
import { artifactLabel } from './resultPresentation';

export interface ArtifactsPanelProps { jobId: string; stage: string; manifest: Manifest | null; }

/** All existing manifest download flags and artifact IDs remain authoritative. */
export function ArtifactsPanel({ jobId, stage, manifest }: ArtifactsPanelProps) {
  if (!manifest) return <p className="panel-empty">此阶段暂无结果文件。</p>;
  return <div className="download-groups">
    {(['data','preview'] as const).map(group => {
      const artifacts = (manifest.artifacts || []).filter(a => (a.role === 'preview' ? 'preview' : 'data') === group);
      if (!artifacts.length) return null;
      return <section key={group}><h4>{group === 'preview' ? '预览文件' : '原生产物与处理数据'}</h4>
        <div className="artifact-list">{artifacts.map(a => <div className="artifact-row" key={a.artifact_id}>
          <span className="artifact-label">{artifactLabel(a, manifest)}</span>
          <span className="artifact-format">{a.path.split('/').pop()}</span>
          {a.download === true ? <a className="btn btn-download" href={api.artifactUrl(jobId, stage, a.artifact_id)} download={a.path.split('/').pop()}>下载</a>
            : <span className="no-download">仅用于页面预览</span>}
        </div>)}</div>
      </section>;
    })}
  </div>;
}
