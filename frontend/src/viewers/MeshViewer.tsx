import { Suspense, useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { FitView } from './FitView';

export interface MeshViewerProps { url: string }
type Mode = 'gray' | 'original' | 'normal';

export function MeshViewer({ url }: MeshViewerProps) {
  const [mode, setMode] = useState<Mode>('gray');
  const [reset, setReset] = useState(0);
  return <div className="viewer-3d mesh-viewer">
    <Canvas camera={{ position: [4, 5, 6], fov: 45 }}>
      <color attach="background" args={['#111820']} />
      <hemisphereLight args={['#ffffff', '#777777', 1.5]} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 20, 8]} intensity={1.5} />
      <directionalLight position={[-12, -4, -6]} intensity={0.8} />
      <Suspense fallback={<Html center>加载 GLB 网格中…</Html>}>
        <Model url={url} mode={mode} reset={reset} />
      </Suspense>
      <OrbitControls makeDefault enableDamping />
    </Canvas>
    <div className="viewer-toolbar">
      <label>显示 <select value={mode} onChange={e => setMode(e.target.value as Mode)}>
        <option value="gray">中性灰实体</option><option value="original">GLB 原始材质</option><option value="normal">法线方向</option>
      </select></label>
      <button className="btn btn-ghost" onClick={() => setReset(v => v + 1)}>重置视角</button>
    </div>
    <div className="viewer-hint">拖拽旋转 · 滚轮缩放 · 右键平移 · 法线颜色表示方向</div>
  </div>;
}

function Model({ url, mode, reset }: { url: string; mode: Mode; reset: number }) {
  const { scene } = useGLTF(url);
  const display = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      if (mode === 'normal') object.material = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide });
      else if (mode === 'gray') object.material = new THREE.MeshStandardMaterial({ color: '#b8b8b8', vertexColors: false, metalness: 0, roughness: 0.9, side: THREE.DoubleSide });
      else object.material = Array.isArray(object.material) ? object.material.map(m => m.clone()) : object.material.clone();
    });
    return clone;
  }, [scene, mode]);
  useEffect(() => () => display.traverse(object => {
    if (object instanceof THREE.Mesh) {
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach(m => m.dispose());
    }
  }), [display]);
  const box = useMemo(() => new THREE.Box3().setFromObject(scene), [scene]);
  return <><primitive object={display} /><FitView box={box} reset={reset} /></>;
}
