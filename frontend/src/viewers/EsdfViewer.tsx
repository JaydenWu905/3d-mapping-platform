import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/api';
import type { GradientPlane } from '../types';
import { PointCloudViewer } from './PointCloudViewer';
import { cloudMetaRows, readSlicesMeta, sliceMetaRows } from './esdfMeta';

export interface EsdfViewerProps {
  jobId: string;
  stage: string;
  slices: string[]; // 来自 manifest.metrics.slices，如 ['xy','xz','yz']
  artifacts: { artifact_id: string; role: string }[];
  /** 整个 manifest.metrics，用于读取 slices_meta（分辨率 / 坐标范围 / 距离范围） */
  metrics?: Record<string, unknown> | null;
}

const PLANE_HINTS: Record<string, string> = {
  xy: '沿 Z 高度切片 · 世界坐标 XY 平面',
  xz: '沿 Y 切片 · 侧视',
  yz: '沿 X 切片 · 侧视',
  '3d': '全空间 ESDF 点云 · 颜色 = 带符号距离',
};

const CLOUD_TAB = '3d';

/**
 * 距离场预览：切片（Distance 底图 + Observed 覆盖 + Gradient 箭头）与 3D 点云两个视图。
 * 所有文件都经 /previews/{artifact_id} 读取，artifact_id 由 manifest 推导；
 * 3D 视图只加载后端额外导出的降采样二进制 esdf_vis_web.ply，原始 PLY 不进入浏览器。
 */
export function EsdfViewer({ jobId, stage, slices, artifacts, metrics }: EsdfViewerProps) {
  const artifactIds = new Set(artifacts.map((a) => a.artifact_id));
  const planes = slices.length > 0 ? slices : ['xy', 'xz', 'yz'].filter((p) => artifactIds.has(`slice_${p}`));
  const hasCloud = artifactIds.has('esdf_web_ply');
  const tabs = hasCloud ? [...planes, CLOUD_TAB] : planes;

  const meta = useMemo(() => readSlicesMeta(metrics), [metrics]);
  const resolutionM = typeof metrics?.resolution_m === 'number' ? metrics.resolution_m : undefined;

  const [plane, setPlane] = useState<string>(tabs[0] ?? 'xy');
  const [showObserved, setShowObserved] = useState(true);
  const [showGradient, setShowGradient] = useState(true);
  const [arrows, setArrows] = useState<Record<string, GradientPlane> | null>(null);
  const [arrowError, setArrowError] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const isCloud = plane === CLOUD_TAB;
  const sliceUrl = (id: string) => (artifactIds.has(id) ? api.previewUrl(jobId, stage, id) : null);
  const hasObserved = artifactIds.has(`observed_${plane}`);
  const hasGradient = artifactIds.has('gradient');

  // 拉取 gradient（一次即可），供所有切片复用
  useEffect(() => {
    if (!hasGradient) return undefined;
    let cancelled = false;
    setArrows(null);
    setArrowError(false);
    api
      .getPreviewJson(jobId, stage, 'gradient')
      .then((d) => {
        if (!cancelled) setArrows(d as Record<string, GradientPlane>);
      })
      .catch(() => {
        if (!cancelled) setArrowError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, stage, hasGradient]);

  // 画图渐变箭头叠加层
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || isCloud || !showGradient || !arrows || !arrows[plane]) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const gp = arrows[plane];
    const W = gp.cols || 480;
    const H = gp.rows || 480;
    canvas.width = W;
    canvas.height = H;
    ctx.clearRect(0, 0, W, H);

    const scale = 1;
    const isVerticalSlice = plane === 'xz' || plane === 'yz';
    ctx.strokeStyle = 'rgba(255,209,84,0.95)';
    ctx.lineWidth = Math.max(1.2, W / 900);
    ctx.fillStyle = 'rgba(255,209,84,0.9)';
    const head = Math.max(3, W / 110);
    for (const a of gp.arrows) {
      const factor = Math.max(0.15, Math.min(2.2, Math.hypot(a.dx, a.dy) * (scale / (gp.magnitude_max || 1)) * 14));
      let x1 = a.x;
      let y1 = a.y;
      let x2 = a.x + a.dx * factor;
      let y2 = a.y + a.dy * factor;
      if (isVerticalSlice) {
        const t = x1;
        x1 = y1;
        y1 = t;
        const t2 = x2;
        x2 = y2;
        y2 = t2;
      }
      if (!isFinite(x1) || !isFinite(y1) || !isFinite(x2) || !isFinite(y2)) continue;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      // 箭头头部
      const ang = Math.atan2(y2 - y1, x2 - x1);
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - head * Math.cos(ang - 0.42), y2 - head * Math.sin(ang - 0.42));
      ctx.lineTo(x2 - head * Math.cos(ang + 0.42), y2 - head * Math.sin(ang + 0.42));
      ctx.closePath();
      ctx.fill();
    }
  }, [arrows, plane, showGradient, isCloud]);

  if (tabs.length === 0) return <div className="viewer-empty">该阶段没有距离场切片数据（metrics.slices 为空）。</div>;

  const baseUrl = isCloud ? null : sliceUrl(`slice_${plane}`);
  const observedUrl = !isCloud && hasObserved ? sliceUrl(`observed_${plane}`) : null;
  const cloudUrl = hasCloud ? api.previewUrl(jobId, stage, 'esdf_web_ply') : null;
  const metaRows = isCloud ? cloudMetaRows(meta) : sliceMetaRows(plane, meta, resolutionM);

  return (
    <div className="esdf-viewer">
      <div className="plane-tabs">
        {tabs.map((p) => (
          <button
            key={p}
            className={`plane-tab ${p === plane ? 'active' : ''}`}
            onClick={() => setPlane(p)}
          >
            {p === CLOUD_TAB ? '3D 点云' : `${p.toUpperCase()} 切片`}
          </button>
        ))}
        <span className="plane-hint">{PLANE_HINTS[plane] ?? ''}</span>
      </div>

      {isCloud ? (
        <div className="esdf-stage esdf-stage-3d">
          {cloudUrl ? (
            <PointCloudViewer url={cloudUrl} meta={meta?.web_preview} legend={meta?.distance_legend_range_m} />
          ) : (
            <div className="esdf-missing">点云预览缺失（esdf_web_ply）</div>
          )}
        </div>
      ) : (
        <>
          <div className="esdf-stage" style={{ aspectRatio: '1 / 1' }}>
            {baseUrl ? (
              <img className="esdf-base" src={baseUrl} alt={`距离场 ${plane}`} />
            ) : (
              <div className="esdf-missing">距离场图片缺失（slice_{plane}）</div>
            )}
            {observedUrl && showObserved ? (
              <img className="esdf-overlay esdf-observed" src={observedUrl} alt={`观测掩码 ${plane}`} />
            ) : null}
            <canvas
              ref={canvasRef}
              className="esdf-overlay esdf-arrows"
              style={{ display: showGradient && arrows && arrows[plane] ? 'block' : 'none' }}
            />
            {arrowError ? <div className="esdf-tip">梯度预览不可用</div> : null}
          </div>

          <div className="overlay-controls">
            <label className="toggle">
              <input type="checkbox" checked={showObserved} onChange={(e) => setShowObserved(e.target.checked)} disabled={!observedUrl} />
              观测掩码
            </label>
            <label className="toggle">
              <input type="checkbox" checked={showGradient && hasGradient} onChange={(e) => setShowGradient(e.target.checked)} disabled={!hasGradient} />
              梯度箭头
            </label>
            <span className="gradient-note">{arrows && arrows[plane] ? `|∇| 最大值 = ${arrows[plane].magnitude_max}` : ''}</span>
          </div>
        </>
      )}

      {metaRows.length > 0 ? (
        <dl className="esdf-meta">
          {metaRows.map((row) => (
            <div className="esdf-meta-row" key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="esdf-legend">距离（m）：红 −1.5 → 紫 0 → 蓝 +1.5。白色无有效预览采样，不能视为自由空间。</p>
      <details className="esdf-explanation"><summary>距离场说明</summary><p>正侧沿原 TSDF 传感器侧。切片仅显示 |d|≤1.5 m 的观测支持域；原生地图计算半径为 2.5 m，未分配或未观测体素均为未知。预览筛选不改变原生产物。3D 视图加载的是后端降采样后的二进制点云（原始 PLY 在下载中）。</p></details>
    </div>
  );
}
