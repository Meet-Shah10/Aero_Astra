/* Ported from orbital-tomb/components/Scene3D.tsx
   Full 3D background: Earth globe + debris field + camera orbit + dolly-in on launch */
import React, { useRef, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import Earth from './Earth';
import DebrisField from './DebrisField';

// Camera orbits slowly and dollies in (150 → 80) when launched
function CameraController({ launched }) {
  const { camera } = useThree();
  const angleRef = useRef(0);
  const currentDistanceRef = useRef(150);
  const startTimeRef = useRef(null);

  useEffect(() => {
    if (launched) {
      startTimeRef.current = null; // reset so it picks up elapsed from scratch
    }
  }, [launched]);

  useFrame((state, delta) => {
    // 1. Slow horizontal orbit 0.05 rad/s
    angleRef.current += 0.05 * delta;

    // 2. Dolly-in on launch: 150 → 80 over 1.5s with easeOutQuart
    let targetDistance = 150;
    if (launched) {
      if (startTimeRef.current === null) {
        startTimeRef.current = state.clock.getElapsedTime();
      }
      const elapsed = state.clock.getElapsedTime() - startTimeRef.current;
      const progress = Math.min(elapsed / 1.5, 1.0);
      const easeProgress = 1 - Math.pow(1 - progress, 4);
      targetDistance = THREE.MathUtils.lerp(150, 80, easeProgress);
    }

    currentDistanceRef.current = THREE.MathUtils.lerp(
      currentDistanceRef.current,
      targetDistance,
      0.08
    );

    const dist = currentDistanceRef.current;
    camera.position.x = Math.sin(angleRef.current) * dist;
    camera.position.z = Math.cos(angleRef.current) * dist;
    camera.position.y = Math.sin(angleRef.current * 0.3) * (dist * 0.18);
    camera.lookAt(0, 0, 0);
  });

  return null;
}

export default function Scene3D({ launched }) {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      width: '100%',
      height: '100%',
      zIndex: 0,
      pointerEvents: 'none',
      background: '#05060F',
    }}>
      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 0, 150], fov: 45 }}
        gl={{ antialias: true, alpha: false }}
        style={{ width: '100%', height: '100%' }}
      >
        <ambientLight intensity={0.1} />
        <directionalLight position={[10, 5, 8]} intensity={1.2} />

        <Earth />
        <DebrisField />

        <CameraController launched={launched} />
      </Canvas>
    </div>
  );
}
