import { useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import * as THREE from 'three';

/** Fit display bounds without transforming source geometry. */
export function FitView({ box, reset }: { box: THREE.Box3; reset: number }) {
  const { camera, controls, size } = useThree();
  useEffect(() => {
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const center = sphere.center;
    const radius = Math.max(sphere.radius, 0.01);
    const perspective = camera as THREE.PerspectiveCamera;
    const vertical = THREE.MathUtils.degToRad(perspective.fov);
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * size.width / size.height);
    const distance = radius / Math.sin(Math.min(vertical, horizontal) / 2) * 1.15;
    camera.position.copy(center).addScaledVector(new THREE.Vector3(0.75, 0.65, 0.85).normalize(), distance);
    perspective.near = Math.max(distance / 10000, 0.0001);
    perspective.far = Math.max(distance + radius * 10, 10);
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    const orbit = controls as unknown as { target: THREE.Vector3; update: () => void } | null;
    orbit?.target.copy(center);
    orbit?.update();
  }, [box, reset, camera, controls, size.width, size.height]);
  return null;
}
