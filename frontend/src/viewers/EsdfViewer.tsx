import { useEffect, useRef, useState } from 'react';
import { api } from '../api/api';
import type { GradientPlane } from '../types';

export interface EsdfViewerProps {
  jobId: string;
  stage: string;
  slices: string[]; // 来自 manifest.metrics.slices，如 ['xy','xz','yz']
  artifacts: { artifact_id: string; role: string }[];
}

const PLANE_HINTS: Record<string, string> = {
  xy: '沿 Z 高度切片 · 房间俯视（viewport 纹理示意）',
  xz: '沿 Y 切片 · 侧视',
  yz: '沿 X 切片 · 侧视',
};

/**
 * 距离场切片预览：Distance 底图 + Observed 二值覆盖 + Gradient 渐变箭头叠加。
 * 全部经 /previews/{artifact_id} 读取，artifact_id 由 manifest 推导（slice_xy / slice_xz / slice_yz / observed_* / gradient）。
 */
export function EsdfViewer({ jobId, stage, slices, artifacts }: EsdfViewerProps) {
  const artifactIds = new Set(artifacts.map((a) => a.artifact_id));
  const planes = slices.length > 0 ? slices : ['xy', 'xz', 'yz'].filter((p) => artifactIds.has(`slice_${p}`));

  const [plane, setPlane] = useState<string>(planes[0] ?? 'xy');
  const [showObserved, setShowObserved] = useState(true);
  const [showGradient, setShowGradient] = useState(true);
  const [arrows, setArrows] = useState<Record<string, GradientPlane> | null>(null);
  const [arrowError, setArrowError] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

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
    if (!canvas || !showGradient || !arrows || !arrows[plane]) return;
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
  }, [arrows, plane, showGradient]);

  if (planes.length === 0) return <div className="viewer-empty">该阶段没有距离场切片数据（metrics.slices 为空）。</div>;

  const baseUrl = sliceUrl(`slice_${plane}`);
  const observedUrl = hasObserved ? sliceUrl(`observed_${plane}`) : null;

  return (
    <div className="esdf-viewer">
      <div className="plane-tabs">
        {planes.map((p) => (
          <button
            key={p}
            className={`plane-tab ${p === plane ? 'active' : ''}`}
            onClick={() => setPlane(p)}
          >
            {p.toUpperCase()} 切片
          </button>
        ))}
        <span className="plane-hint">{PLANE_HINTS[plane] ?? ''}</span>
      </div>

      <div className="esdf-stage" style={{ aspectRatio: '1 / 1' }}>
        {baseUrl ? (
          <img className="esdf-base" src={baseUrl} alt={`distance ${plane}`} />
        ) : (
          <div className="esdf-missing">distance 图片缺失（slice_{plane}）</div>
        )}
        {observedUrl && showObserved ? (
          <img className="esdf-overlay esdf-observed" src={observedUrl} alt={`observed ${plane}`} />
        ) : null}
        <canvas
          ref={canvasRef}
          className="esdf-overlay esdf-arrows"
          style={{ display: showGradient && arrows && arrows[plane] ? 'block' : 'none' }}
        />
        {arrowError ? <div className="esdf-tip">gradient 预览不可用</div> : null}
      </div>

      <div className="overlay-controls">
        <label className="toggle">
          <input type="checkbox" checked={showObserved} onChange={(e) => setShowObserved(e.target.checked)} disabled={!observedUrl} />
          观测掩码 (Observed)
        </label>
        <label className="toggle">
          <input type="checkbox" checked={showGradient} onChange={(e) => setShowGradient(e.target.checked)} disabled={!hasGradient} />
          梯度箭头 (Gradient)
        </label>
        <span className="gradient-note">{arrows && arrows[plane] ? `|∇| max = ${arrows[plane].magnitude_max}` : ''}</span>
      </div>

      <p className="esdf-legend">暖色 = 靠近障碍物表面（距离小），冷色 = 离表面远 · 箭头指向距离梯度上升方向</p>
    </div>
  );
}