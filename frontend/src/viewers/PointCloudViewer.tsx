import { useEffect, useMemo, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { FitView } from './FitView';
import type { ParsedPointCloud, PointCloudResponse } from './esdfPlyWorker';
import type { AxisRange, EsdfWebPreviewMeta } from '../types';

export interface PointCloudViewerProps {
  /** preview/esdf_vis_web.ply 的 /previews/{artifact_id} 地址 */
  url: string;
  /** manifest.metrics.slices_meta.web_preview */
  meta?: EsdfWebPreviewMeta | null;
  /** 距离图例范围（米），默认 ±1.5 */
  legend?: AxisRange;
}

const DEFAULT_LEGEND: AxisRange = [-1.5, 1.5];

/** 已解析结果按 URL 缓存：切换切片标签再切回来不重复下载/解析。 */
const cloudCache = new Map<string, ParsedPointCloud>();

function usePointCloud(url: string) {
  const [data, setData] = useState<ParsedPointCloud | null>(() => cloudCache.get(url) ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const cached = cloudCache.get(url);
    if (cached) {
      setData(cached);
      setError(null);
      return undefined;
    }
    setData(null);
    setError(null);
    const worker = new Worker(new URL('./esdfPlyWorker.ts', import.meta.url), { type: 'module' });
    let cancelled = false;
    worker.onmessage = (event: MessageEvent<PointCloudResponse>) => {
      if (cancelled) return;
      const message = event.data;
      if (!message.ok) {
        setError(message.error);
        return;
      }
      const cloud: ParsedPointCloud = {
        positions: message.positions,
        distances: message.distances,
        colors: message.colors,
        pointCount: message.pointCount,
        hasDistance: message.hasDistance,
        hasColor: message.hasColor,
      };
      cloudCache.set(url, cloud);
      setData(cloud);
    };
    worker.onerror = () => {
      if (!cancelled) setError('点云解析失败（Worker 异常）');
    };
    worker.postMessage({ url });
    return () => {
      cancelled = true;
      worker.terminate();
    };
  }, [url]);

  return { data, error };
}

const vertexShader = /* glsl */ `
  attribute vec3 color;
  attribute float distance;
  uniform float uPointSize;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vDistance;
  void main() {
    vColor = color;
    vDistance = distance;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uPointSize * uPixelRatio;
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const fragmentShader = /* glsl */ `
  uniform bool uUseVertexColor;
  uniform float uLegendMin;
  uniform float uLegendMax;
  varying vec3 vColor;
  varying float vDistance;
  void main() {
    if (uUseVertexColor) {
      gl_FragColor = vec4(vColor, 1.0);
      return;
    }
    // 与切片 PNG 完全一致的映射：红(−1.5) → 紫(0) → 蓝(+1.5)
    float t = clamp((vDistance - uLegendMin) / (uLegendMax - uLegendMin), 0.0, 1.0);
    gl_FragColor = vec4(vec3(1.0 - t, 0.0, t), 1.0);
  }
`;

function Cloud({ data, pointSize, useVertexColor, legend }: {
  data: ParsedPointCloud;
  pointSize: number;
  useVertexColor: boolean;
  legend: AxisRange;
}) {
  const dpr = useThree((state) => state.viewport.dpr);

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
    g.setAttribute('distance', new THREE.BufferAttribute(data.distances, 1));
    g.setAttribute('color', new THREE.BufferAttribute(data.colors, 3, true));
    g.computeBoundingBox();
    g.computeBoundingSphere();
    return g;
  }, [data]);

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uPointSize: { value: 2.0 },
      uPixelRatio: { value: 1 },
      uUseVertexColor: { value: false },
      uLegendMin: { value: DEFAULT_LEGEND[0] },
      uLegendMax: { value: DEFAULT_LEGEND[1] },
    },
  }), []);

  useEffect(() => {
    material.uniforms.uPointSize.value = pointSize;
    material.uniforms.uPixelRatio.value = dpr;
    material.uniforms.uUseVertexColor.value = useVertexColor && data.hasColor;
    material.uniforms.uLegendMin.value = legend[0];
    material.uniforms.uLegendMax.value = legend[1];
  }, [material, pointSize, dpr, useVertexColor, data.hasColor, legend]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  return <points geometry={geometry} material={material} frustumCulled={false} />;
}

export function PointCloudViewer({ url, meta, legend }: PointCloudViewerProps) {
  const { data, error } = usePointCloud(url);
  const [pointSize, setPointSize] = useState(2);
  const [useVertexColor, setUseVertexColor] = useState(false);
  const [reset, setReset] = useState(0);

  const box = useMemo(() => {
    const box3 = new THREE.Box3();
    if (!data) return box3;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
    g.computeBoundingBox();
    if (g.boundingBox) box3.copy(g.boundingBox);
    g.dispose();
    return box3;
  }, [data]);

  const legendRange = legend ?? DEFAULT_LEGEND;
  const sourceCount = meta?.source_point_count;
  const ratio = meta?.downsample_ratio;

  return (
    <div className="point-cloud-viewer">
      <Canvas dpr={[1, 2]} camera={{ position: [0, 8, 16], fov: 45, near: 0.05, far: 5000 }}>
        <color attach="background" args={['#0b1118']} />
        <ambientLight intensity={0.6} />
        {data ? (
          <Cloud data={data} pointSize={pointSize} useVertexColor={useVertexColor} legend={legendRange} />
        ) : null}
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
        {data ? <FitView box={box} reset={reset} /> : null}
      </Canvas>

      {!data && !error ? (
        <div className="point-cloud-loading"><span>正在加载点云…</span></div>
      ) : null}
      {error ? <div className="point-cloud-error">点云加载失败：{error}</div> : null}

      <div className="viewer-toolbar point-cloud-toolbar">
        <label className="toggle">
          <input
            type="checkbox"
            checked={useVertexColor || Boolean(data && !data.hasDistance)}
            disabled={!data?.hasColor || !data?.hasDistance}
            onChange={(event) => setUseVertexColor(event.target.checked)}
          />
          原始顶点色
        </label>
        <label className="toggle point-size">
          点大小
          <input
            type="range"
            min={1}
            max={6}
            step={0.5}
            value={pointSize}
            onChange={(event) => setPointSize(Number(event.target.value))}
          />
        </label>
        <button type="button" className="btn" onClick={() => setReset((v) => v + 1)}>
          重置视角
        </button>
      </div>

      <div className="point-cloud-footer">
        <span className="point-cloud-hint">拖拽旋转 · 滚轮缩放 · 右键平移 · 颜色 = 带符号距离</span>
        <span className="point-cloud-count">
          {data ? `${data.pointCount.toLocaleString('zh-CN')} 点` : (meta?.format ?? 'binary PLY')}
          {data && sourceCount ? ` · 源 ${sourceCount.toLocaleString('zh-CN')} 点` : ''}
          {data && typeof ratio === 'number' && ratio < 0.999 ? `（抽样 ${(ratio * 100).toFixed(1)}%）` : ''}
          {data && !data.hasDistance ? ' · 无 distance 属性' : ''}
        </span>
      </div>
    </div>
  );
}
