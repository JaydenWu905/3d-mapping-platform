import { Suspense, useEffect } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';

export interface MeshViewerProps {
  url: string; // /previews/{artifact_id} 的 GLB 地址（从不直接拼接文件路径）
}

/** 表面网格 GLB 预览：加载后自动把相机对准模型包围盒。 */
export function MeshViewer({ url }: MeshViewerProps) {
  return (
    <div className="viewer-3d mesh-viewer">
      <Canvas camera={{ position: [4, 5, 6], fov: 45 }}>
        <color attach="background" args={['#0b1118']} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[10, 20, 8]} intensity={1.1} />
        <directionalLight position={[-12, -4, -6]} intensity={0.35} color="#7fb3d9" />
        <Suspense
          fallback={
            <Html center>
              <div className="viewer-loading-inline">加载 GLB 网格中…</div>
            </Html>
          }
        >
          <Model url={url} />
        </Suspense>
        <OrbitControls makeDefault enableDamping />
      </Canvas>
      <div className="viewer-hint">拖拽旋转 · 滚轮缩放 · 右键平移</div>
    </div>
  );
}

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as {
    target: THREE.Vector3;
    update: () => void;
  } | null;

  useEffect(() => {
    const box = new THREE.Box3().setFromObject(scene);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z) * 0.55;
    const d = Math.max(r * 2.4, 0.5);
    camera.position.set(center.x + d * 0.7, center.y + d * 0.55, center.z + d * 1.0);
    camera.far = Math.max(d * 60, 10);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.set(center.x, center.y - r * 0.1, center.z);
      controls.update();
    }
  }, [scene, camera, controls]);

  return <primitive object={scene} />;
}