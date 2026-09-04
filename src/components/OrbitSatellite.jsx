import { useMemo, useEffect, useLayoutEffect, useRef, useState, Suspense } from 'react';
import { motion, useMotionValue, useTransform, animate } from 'motion/react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useGLTF, Center } from '@react-three/drei';
import * as THREE from 'three';
import './OrbitSatellite.css';

function generateEllipsePath(cx, cy, rx, ry) {
  return `M ${cx - rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx + rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx - rx} ${cy}`;
}

// Normalizes the raw GLB to a fixed apparent size so wide geometry (solar
// panels) can never exceed the square canvas frustum — unlike a flat scale
// factor, this measures the model's actual bounding sphere first.
function MiniSatellite({ url }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => scene.clone(true), [scene]);
  const ref = useRef();

  const fitScale = useMemo(() => {
    const box = new THREE.Box3().setFromObject(cloned);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    // 0.6 = target apparent radius in scene units, leaves margin inside frame
    return 0.6 / (sphere.radius || 1);
  }, [cloned]);

  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += 0.6 * dt;
  });

  return (
    <group ref={ref}>
      <Center scale={fitScale}>
        <primitive object={cloned} />
      </Center>
    </group>
  );
}

// Angle mapping: angle = PI + (offset/100)*2*PI
//   offset 0  -> left  (cx-rx, cy)
//   offset 25 -> top   (cx, cy-ry)   behind globe
//   offset 50 -> right (cx+rx, cy)
//   offset 75 -> bottom (cx, cy+ry)  in front
function OrbitItem({ index, totalItems, cx, cy, rx, ry, itemSize, rotation, progress }) {
  const itemOffset = (index / totalItems) * 100;

  const x = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    const angle = Math.PI + (offset / 100) * 2 * Math.PI;
    return cx + rx * Math.cos(angle) - itemSize / 2;
  });

  const y = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    const angle = Math.PI + (offset / 100) * 2 * Math.PI;
    return cy + ry * Math.sin(angle) - itemSize / 2;
  });

  const opacity = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    if (offset > 6 && offset < 44) return 0;
    if (offset > 3 && offset <= 6) return 1 - (offset - 3) / 3;
    if (offset >= 44 && offset < 47) return (offset - 44) / 3;
    return 1;
  });

  const scale = useTransform(progress, (p) => {
    const offset = (((p + itemOffset) % 100) + 100) % 100;
    return 1.0 - 0.3 * Math.sin((offset / 100) * 2 * Math.PI);
  });

  return (
    <motion.div
      className="orbit-sat-item"
      style={{ width: itemSize, height: itemSize, x, y, opacity, scale }}
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
  const [containerScale, setContainerScale] = useState(null);

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
      setContainerScale(containerRef.current.clientWidth / baseWidth);
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
    <div ref={containerRef} className="orbit-sat-container" aria-hidden="true">
      <div
        className="orbit-sat-scaling orbit-sat-scaling--responsive"
        style={{
          width: baseWidth,
          height: baseWidth,
          transform: containerScale !== null
            ? `translate(-50%, calc(-50% - 60px)) scale(${containerScale})`
            : undefined,
          visibility: containerScale === null ? 'hidden' : undefined,
        }}
      >
        <div
          className="orbit-sat-rotation"
          style={{ transform: `rotate(${rotation}deg)` }}
        >
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
              cx={cx}
              cy={cy}
              rx={radiusX}
              ry={radiusY}
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
