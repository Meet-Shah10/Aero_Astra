/* Globe3D — a real textured 3D Earth (day map + normal map + specular map +
   cloud layer + atmosphere glow), replacing the old 2D canvas dot-matrix
   globe. Textures are bundled locally in public/textures/earth/ (sourced
   from three.js's own official example assets) rather than fetched from a
   CDN at runtime — same reasoning as the landmass GeoJSON fix: no
   cross-origin latency, no risk of a third-party host going away mid-demo. */
import { Suspense, useRef, useMemo } from 'react';
import { Canvas, useFrame, useLoader } from '@react-three/fiber';
import * as THREE from 'three';

const EARTH_AXIAL_TILT = 0.41; // ~23.5 degrees, radians

function StarField() {
  const ref = useRef();
  const count = 2600;

  const [positions, sizes] = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const siz = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      // Distribute on a thick spherical shell well outside the globe/camera.
      const r = 340 + Math.random() * 260;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = r * Math.cos(phi);
      siz[i] = 0.6 + Math.random() * 1.6;
    }
    return [pos, siz];
  }, []);

  // Slight, slow drift — "moving a little bit", not a visible sweep.
  useFrame((_, dt) => {
    if (ref.current) {
      ref.current.rotation.y += 0.004 * dt;
      ref.current.rotation.x += 0.0012 * dt;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-size" args={[sizes, 1]} />
      </bufferGeometry>
      <pointsMaterial
        size={1.3}
        sizeAttenuation
        color="#dfe6ff"
        transparent
        opacity={0.85}
        depthWrite={false}
      />
    </points>
  );
}

function Earth({ isRotating }) {
  const groupRef = useRef();
  const cloudRef = useRef();

  const [dayMap, normalMap, specMap, cloudMap] = useLoader(THREE.TextureLoader, [
    '/textures/earth/earth_atmos_2048.jpg',
    '/textures/earth/earth_normal_2048.jpg',
    '/textures/earth/earth_specular_2048.jpg',
    '/textures/earth/earth_clouds_1024.png',
  ]);

  // Very slow — this is a background element, not the focal point.
  useFrame((_, dt) => {
    if (!isRotating) return;
    if (groupRef.current) groupRef.current.rotation.y += 0.014 * dt;
    if (cloudRef.current) cloudRef.current.rotation.y += 0.019 * dt; // clouds drift a touch faster — parallax
  });

  return (
    <group ref={groupRef} rotation={[EARTH_AXIAL_TILT, 0, 0]}>
      <mesh>
        <sphereGeometry args={[2, 96, 96]} />
        <meshPhongMaterial
          map={dayMap}
          normalMap={normalMap}
          normalScale={new THREE.Vector2(0.85, 0.85)}
          specularMap={specMap}
          specular={new THREE.Color('#3a6b9c')}
          shininess={10}
        />
      </mesh>

      <mesh ref={cloudRef}>
        <sphereGeometry args={[2.015, 96, 96]} />
        <meshLambertMaterial
          map={cloudMap}
          transparent
          opacity={0.35}
          depthWrite={false}
        />
      </mesh>

      {/* Atmosphere rim glow — backside-rendered, additive-ish soft blue halo */}
      <mesh scale={1.045}>
        <sphereGeometry args={[2, 64, 64]} />
        <meshBasicMaterial color="#5aa7ff" transparent opacity={0.1} side={THREE.BackSide} />
      </mesh>
      <mesh scale={1.09}>
        <sphereGeometry args={[2, 48, 48]} />
        <meshBasicMaterial color="#3d7fd6" transparent opacity={0.05} side={THREE.BackSide} />
      </mesh>
    </group>
  );
}

export default function Globe3D({ isRotating = true }) {
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0, 6.2], fov: 42 }}
      gl={{ antialias: true, alpha: true }}
      style={{ width: '100%', height: '100%' }}
    >
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 2, 5]} intensity={1.7} color="#fff5e6" />
      <directionalLight position={[-4, -1, -3]} intensity={0.15} color="#4a6fa5" />
      <StarField />
      <Suspense fallback={null}>
        <Earth isRotating={isRotating} />
      </Suspense>
    </Canvas>
  );
}
