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

  const opacity = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    // offset 0 is left, 25 is top(back), 50 is right, 75 is bottom(front)
    // Globe blocks roughly from offset 6 to 44
    if (offset > 6 && offset < 44) return 0;
    // Fade out smoothly at the edges
    if (offset > 3 && offset <= 6) return 1 - (offset - 3) / 3;
    if (offset >= 44 && offset < 47) return (offset - 44) / 3;
    return 1;
  });

  const scale = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    // Sinusoidal scaling for 3D depth: smallest at back (25), largest at front (75)
    return 1.0 - 0.3 * Math.sin((offset / 100) * 2 * Math.PI);
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
        opacity,
        scale,
      }}
    >
      <div style={{ transform: `rotate(${-rotation}deg)`, width: '100%', height: '100%' }}>
        <Canvas
          dpr={[1, 1.5]}
          camera={{ position: [0, 0, 1.8], fov: 45 }}
          gl={{ antialias: true, alpha: true }}
          style={{ width: '100%', height: '100%', background: 'transparent' }}
        >
          <ambientLight intensity={0.8} />
          <directionalLight position={[3, 3, 3]} intensity={2.5} />
          <directionalLight position={[-2, 1, -1]} intensity={1.5} />
          <pointLight position={[0, 0, 2]} intensity={2} color="#00FF88" distance={5} />
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
          // Move the orbit up by 60px (or adjust Y translation)
          transform: scale !== null ? `translate(-50%, calc(-50% - 60px)) scale(${scale})` : undefined,
          visibility: scale === null ? 'hidden' : undefined,
        }}
      >
        <motion.div
          className="orbit-sat-rotation"
          style={{ transform: `rotate(${rotation}deg)` }}
        >
          {/* Orbit ring — subtle dashed ellipse with depth fade */}
          <svg
            width="100%"
            height="100%"
            viewBox={`0 0 ${baseWidth} ${baseWidth}`}
            className="orbit-sat-path-svg"
            style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
          >
            <defs>
              <linearGradient id="orbit-fade" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="35%" stopColor="rgba(255,255,255,0)" />
                <stop offset="50%" stopColor="rgba(255,255,255,0.15)" />
                <stop offset="65%" stopColor="rgba(255,255,255,0.4)" />
                <stop offset="100%" stopColor="rgba(255,255,255,0.4)" />
              </linearGradient>
            </defs>
            <path
              d={path}
              fill="none"
              stroke="url(#orbit-fade)"
              strokeWidth="1.5"
              strokeDasharray="4 6"
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
        </motion.div>
      </div>
    </div>
  );
}
