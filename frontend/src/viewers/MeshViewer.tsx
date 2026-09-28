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
      <Canvas camera={{ position: [4, 5, 6], fov: 45 }} gl={{ toneMapping: THREE.ACESFilmicToneMapping }}>
        <color attach="background" args={['#111820']} />
        <hemisphereLight args={['#dcecff', '#26313b', 1.25]} />
        <ambientLight intensity={0.35} />
        <directionalLight position={[10, 20, 8]} intensity={1.5} />
        <directionalLight position={[-12, -4, -6]} intensity={0.55} color="#91c7ef" />
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
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const geometry = object.geometry as THREE.BufferGeometry;
      if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        material.side = THREE.DoubleSide;
        material.needsUpdate = true;
      }
    });
    const box = new THREE.Box3().setFromObject(scene);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const perspective = camera as THREE.PerspectiveCamera;
    const verticalFov = THREE.MathUtils.degToRad(perspective.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * perspective.aspect);
    const limitingFov = Math.min(verticalFov, horizontalFov);
    const distance = Math.max(sphere.radius / Math.sin(limitingFov / 2) * 1.15, 0.5);
    const direction = new THREE.Vector3(0.75, -0.85, 0.65).normalize();
    camera.position.copy(center).addScaledVector(direction, distance);
    perspective.near = Math.max(distance / 10_000, 0.001);
    perspective.far = Math.max(distance + sphere.radius * 10, 10);
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [scene, camera, controls]);

  return <primitive object={scene} />;
}
