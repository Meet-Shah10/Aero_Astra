/* Ported from orbital-tomb/components/Earth.tsx */
import React, { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export default function Earth() {
  const groupRef = useRef(null);
  const coreRef = useRef(null);

  useFrame((state, delta) => {
    const rotSpeed = 0.012 * delta;
    if (groupRef.current) {
      groupRef.current.rotation.y += rotSpeed;
    }
    if (coreRef.current) {
      coreRef.current.rotation.y += rotSpeed * 0.5;
    }
  });

  return (
    <group ref={groupRef}>
      {/* 1. Dark translucent core */}
      <mesh ref={coreRef}>
        <sphereGeometry args={[50, 32, 32]} />
        <meshBasicMaterial color="#030612" transparent opacity={0.85} />
      </mesh>

      {/* 2. Cyan wireframe grid */}
      <mesh>
        <sphereGeometry args={[50.2, 24, 24]} />
        <meshBasicMaterial
          color="#00E5FF"
          wireframe
          transparent
          opacity={0.12}
          depthWrite={false}
        />
      </mesh>

      {/* 3. Equator ring */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[50.3, 50.5, 64]} />
        <meshBasicMaterial
          color="#00E5FF"
          side={THREE.DoubleSide}
          transparent
          opacity={0.3}
          depthWrite={false}
        />
      </mesh>

      {/* 4. Atmospheric glow halo */}
      <mesh>
        <sphereGeometry args={[52.0, 32, 32]} />
        <meshBasicMaterial
          color="#00E5FF"
          transparent
          opacity={0.06}
          side={THREE.BackSide}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}
