import type { Manifest } from '../types';
import { previewDescription, resultMetrics } from './resultPresentation';

export function ResultDetails({ stage, manifest }: { stage: string; manifest: Manifest | null }) {
  if (!manifest) return <p>此阶段尚未生成结果。</p>;
  return <div className="result-details">
    <p>{previewDescription(stage, manifest)}</p>
    <div className="metrics">{resultMetrics(stage, manifest).map(row => <div className="metric" key={row.label}>
      <span className="metric-key">{row.label}</span><span className="metric-val">{row.value}</span>
    </div>)}</div>
  </div>;
}
export function RawResultDetails({ manifest }: { manifest: Manifest | null }) {
  if (!manifest) return null;
  return <details className="raw-result"><summary>完整原始指标与文件记录</summary>
    <pre className="technical-json">{JSON.stringify(manifest, null, 2)}</pre>
  </details>;
}
