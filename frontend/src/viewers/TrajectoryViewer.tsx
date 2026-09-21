import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Line, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { api } from '../api/api';
import type { TrajectoryData } from '../types';

export interface TrajectoryViewerProps {
  jobId: string;
  stage: string;
}

type P3 = [number, number, number];

/**
 * 位姿轨迹预览：从 preview 目录按 artifact_id='trajectory_model' 读取 JSON。
 * 采用"阶段键 → 查看器"的固定映射（pose → 本组件），不涉及任何算法名分支。
 * 坐标系：世界 Z-up → three Y-up，即 three = (world.z, world.y) 上翻 → (x, z, y)。
 */
export function TrajectoryViewer({ jobId, stage }: TrajectoryViewerProps) {
  const [traj, setTraj] = useState<TrajectoryData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTraj(null);
    setError(false);
    api
      .getPreviewJson(jobId, stage, 'trajectory_model')
      .then((d) => {
        if (!cancelled) setTraj(d as TrajectoryData);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, stage]);

  if (error) return <div className="viewer-empty">无法加载轨迹预览（trajectory_model 缺失）</div>;
  if (!traj) return <div className="viewer-empty">加载轨迹中…</div>;

  const pts: P3[] = (traj.points ?? []).map((p) => [p.x, p.z, p.y]);

  if (pts.length < 2) return <div className="viewer-empty">轨迹点不足，无法渲染。</div>;

  return (
    <div className="viewer-3d">
      <Canvas camera={{ position: [2, 4, 5], fov: 50 }}>
        <color attach="background" args={['#0b1118']} />
        <TrajectoryScene points={pts} />
        <OrbitControls makeDefault enableDamping />
      </Canvas>
      <div className="viewer-hint">拖拽旋转 · 滚轮缩放 · 右键平移 · 绿=起点 黄=朝向 红=终点</div>
      <div className="viewer-count">frames: {traj.frame_count}</div>
    </div>
  );
}

function TrajectoryScene({ points }: { points: P3[] }) {
  const { center, radius, groundY } = useMemo(() => {
    const min = new THREE.Vector3(Infinity, Infinity, Infinity);
    const max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
    for (const p of points) {
      min.min(new THREE.Vector3(p[0], p[1], p[2]));
      max.max(new THREE.Vector3(p[0], p[1], p[2]));
    }
    const c = min.clone().add(max).multiplyScalar(0.5);
    const r = (Math.max(max.x - min.x, max.y - min.y, max.z - min.z) || 1) * 0.5;
    return { center: c, radius: r || 1, groundY: min.y };
  }, [points]);

  const tickLine = useMemo(() => {
    // 用原生 THREE.Line 而非 JSX <line>：后者会被 React 的 SVG line 类型抢占，产生类型冲突。
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buildOrientationTicks(points)), 3));
    return new THREE.Line(g, new THREE.LineBasicMaterial({ color: '#f5b942' }));
  }, [points]);

  const start = points[0];
  const end = points[points.length - 1];

  return (
    <>
      {/* 世界 FLU → 显示坐标已在上层映射；网格绘制在 floor 平面 (world z = 0) */}
      <gridHelper args={[radius * 4, Math.max(10, Math.round(radius * 6)), '#3a5a70', '#22303c']} position={[center.x, groundY, center.z]} />

      <Line points={points} color="#3fc1ff" lineWidth={2} />

      <primitive object={tickLine} />

      <mesh position={start}>
        <sphereGeometry args={[radius * 0.15, 16, 16]} />
        <meshBasicMaterial color="#4ade80" />
      </mesh>
      <mesh position={end}>
        <sphereGeometry args={[radius * 0.15, 16, 16]} />
        <meshBasicMaterial color="#ff5a5a" />
      </mesh>
    </>
  );
}

/** 每 N 帧沿轨迹切线画一小段朝向短线（不解析 quaternion，避免格式假设）。 */
function buildOrientationTicks(points: P3[], step = 6, len = 0.45): number[] {
  const arr: number[] = [];
  for (let i = 0; i < points.length - 1; i += step) {
    const a = points[i];
    const b = points[i + 1];
    const d = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    if (d < 1e-9) continue;
    arr.push(
      a[0], a[1], a[2],
      a[0] + ((b[0] - a[0]) / d) * len,
      a[1] + ((b[1] - a[1]) / d) * len,
      a[2] + ((b[2] - a[2]) / d) * len,
    );
  }
  return arr;
}