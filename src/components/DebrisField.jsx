/* Ported from orbital-tomb/components/DebrisField.tsx */
import React, { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export default function DebrisField() {
  const groupRef = useRef(null);

  // 1950 white debris particles avoiding Earth core
  const debrisData = useMemo(() => {
    const count = 1950;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      let x = (Math.random() - 0.5) * 200;
      let y = (Math.random() - 0.5) * 200;
      let z = (Math.random() - 0.5) * 200;
      const dist = Math.sqrt(x * x + y * y + z * z);
      if (dist < 55) {
        const factor = 55 / dist;
        x *= factor; y *= factor; z *= factor;
      }
      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;
    }
    return positions;
  }, []);

  // 25 cyan satellite particles
  const cyanSatData = useMemo(() => {
    const count = 25;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      let x = (Math.random() - 0.5) * 200;
      let y = (Math.random() - 0.5) * 200;
      let z = (Math.random() - 0.5) * 200;
      const dist = Math.sqrt(x * x + y * y + z * z);
      if (dist < 60) {
        const factor = 60 / dist;
        x *= factor; y *= factor; z *= factor;
      }
      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;
    }
    return positions;
  }, []);

  // 25 magenta satellite particles
  const magentaSatData = useMemo(() => {
    const count = 25;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      let x = (Math.random() - 0.5) * 200;
      let y = (Math.random() - 0.5) * 200;
      let z = (Math.random() - 0.5) * 200;
      const dist = Math.sqrt(x * x + y * y + z * z);
      if (dist < 60) {
        const factor = 60 / dist;
        x *= factor; y *= factor; z *= factor;
      }
      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;
    }
    return positions;
  }, []);

  // Slow rotation
  useFrame((state, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += 0.02 * delta;
    }
  });

  return (
    <group ref={groupRef}>
      {/* White debris */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[debrisData, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.05} color="#FFFFFF" transparent opacity={0.6} depthWrite={false} />
      </points>

      {/* Cyan satellites */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[cyanSatData, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.35} color="#00E5FF" transparent opacity={0.9} depthWrite={false} />
      </points>

      {/* Magenta satellites */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[magentaSatData, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.35} color="#FF006E" transparent opacity={0.9} depthWrite={false} />
      </points>
    </group>
  );
}
