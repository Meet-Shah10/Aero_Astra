/* OrbitSatellite — renders a small 3D satellite GLB model orbiting
   around the globe on the landing page using CSS offset-path animation.
   Based on OrbitImages by Dominik Koch, adapted for a single 3D model. */

import { useMemo, useEffect, useLayoutEffect, useRef, useState, Suspense } from 'react';
import { motion, useMotionValue, useTransform, animate } from 'motion/react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import './OrbitSatellite.css';

/* ── path generators ────────────────────────────────────────────── */
function generateEllipsePath(cx, cy, rx, ry) {
  return `M ${cx - rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx + rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx - rx} ${cy}`;
}

/* ── Tiny inline satellite mesh ─────────────────────────────────── */
function MiniSatellite({ url }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => {
    const c = scene.clone(true);
    // Normalise into a unit sphere
    const box = new THREE.Box3().setFromObject(c);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const s = 1 / (sphere.radius * 2);
    c.position.set(-sphere.center.x * s, -sphere.center.y * s, -sphere.center.z * s);
    c.scale.setScalar(s);
    return c;
  }, [scene]);

  const ref = useRef();
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += 0.6 * dt;
  });

  return (
    <group ref={ref}>
      <primitive object={cloned} />
    </group>
  );
}

/* ── Single orbit item ──────────────────────────────────────────── */
function OrbitItem({ index, totalItems, path, itemSize, rotation, progress }) {
  const itemOffset = (index / totalItems) * 100;

  const offsetDistance = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    return `${offset}%`;
  });

  return (
    <motion.div
      className="orbit-sat-item"
      style={{
        width: itemSize,
        height: itemSize,
        offsetPath: `path("${path}")`,
        offsetRotate: '0deg',
        offsetAnchor: 'center center',
        offsetDistance,
      }}
    >
      <div style={{ transform: `rotate(${-rotation}deg)`, width: '100%', height: '100%' }}>
        <Canvas
          dpr={[1, 1.5]}
          camera={{ position: [0, 0, 1.8], fov: 45 }}
          gl={{ antialias: true, alpha: true }}
          style={{ width: '100%', height: '100%', background: 'transparent' }}
        >
          <ambientLight intensity={0.4} />
          <directionalLight position={[3, 3, 3]} intensity={1.5} />
          <directionalLight position={[-2, 1, -1]} intensity={0.5} />
          <Suspense fallback={null}>
            <MiniSatellite url="/simple_satellite_low_poly_free.glb" />
          </Suspense>
        </Canvas>
      </div>
    </motion.div>
  );
}

/* ── Main component ─────────────────────────────────────────────── */
export default function OrbitSatellite({
  count = 1,
  baseWidth = 900,
  radiusX = 380,
  radiusY = 120,
  rotation = -12,
  duration = 20,
  itemSize = 80,
}) {
  const containerRef = useRef(null);
  const [scale, setScale] = useState(null);

  const cx = baseWidth / 2;
  const cy = baseWidth / 2;

  const path = useMemo(
    () => generateEllipsePath(cx, cy, radiusX, radiusY),
    [cx, cy, radiusX, radiusY]
  );

  useLayoutEffect(() => {
    if (!containerRef.current) return;
    const updateScale = () => {
      if (!containerRef.current) return;
      setScale(containerRef.current.clientWidth / baseWidth);
    };
    updateScale();
    const observer = new ResizeObserver(updateScale);
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [baseWidth]);

  const progress = useMotionValue(0);

  useEffect(() => {
    const controls = animate(progress, 100, {
      duration,
      ease: 'linear',
      repeat: Infinity,
      repeatType: 'loop',
    });
    return () => controls.stop();
  }, [progress, duration]);

  return (
    <div
      ref={containerRef}
      className="orbit-sat-container"
      aria-hidden="true"
    >
      <div
        className="orbit-sat-scaling orbit-sat-scaling--responsive"
        style={{
          width: baseWidth,
          height: baseWidth,
          transform: scale !== null ? `translate(-50%, -50%) scale(${scale})` : undefined,
          visibility: scale === null ? 'hidden' : undefined,
        }}
      >
        <div
          className="orbit-sat-rotation"
          style={{ transform: `rotate(${rotation}deg)` }}
        >
          {/* Orbit ring — subtle dashed ellipse */}
          <svg
            width="100%"
            height="100%"
            viewBox={`0 0 ${baseWidth} ${baseWidth}`}
            className="orbit-sat-path-svg"
          >
            <path
              d={path}
              fill="none"
              stroke="rgba(255,255,255,0.06)"
              strokeWidth={1}
              strokeDasharray="6 8"
            />
          </svg>

          {Array.from({ length: count }).map((_, i) => (
            <OrbitItem
              key={i}
              index={i}
              totalItems={count}
              path={path}
              itemSize={itemSize}
              rotation={rotation}
              progress={progress}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
