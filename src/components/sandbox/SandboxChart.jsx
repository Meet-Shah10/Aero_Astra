/**
 * SandboxChart.jsx
 * ─────────────────
 * A lightweight SVG line chart using raw d3-scale (already in node_modules via d3).
 * Renders two series (Run A in cyan, Run B in orange) with a fault-onset marker.
 * No recharts dependency — uses only d3 for scales, everything else is React SVG.
 */
import React, { useMemo } from 'react';
import * as d3 from 'd3';

const COLORS = { A: '#00E5A0', B: '#FFA040' };
const PAD = { top: 10, right: 12, bottom: 28, left: 44 };

export default function SandboxChart({
  label,
  unit = '',
  framesA = [],
  framesB = [],
  accessor,        // (frame) => number
  faultOnsetT,     // seconds — draw vertical marker if set
  duration = 900,
  width = 260,
  height = 110,
  yMin,
  yMax,
}) {
  const W = width  - PAD.left - PAD.right;
  const H = height - PAD.top  - PAD.bottom;

  const allValues = useMemo(() => {
    const va = framesA.map(accessor).filter(Number.isFinite);
    const vb = framesB.map(accessor).filter(Number.isFinite);
    return [...va, ...vb];
  }, [framesA, framesB, accessor]);

  const xScale = useMemo(
    () => d3.scaleLinear().domain([0, duration]).range([0, W]),
    [duration, W]
  );

  const localMin = allValues.length ? Math.min(...allValues) : 0;
  const localMax = allValues.length ? Math.max(...allValues) : 1;
  const padding  = (localMax - localMin) * 0.12 || 0.1;

  const yScale = useMemo(
    () => d3.scaleLinear()
      .domain([yMin ?? localMin - padding, yMax ?? localMax + padding])
      .range([H, 0]),
    [localMin, localMax, padding, yMin, yMax, H]
  );

  const buildPath = (frames, color) => {
    if (frames.length < 2) return null;
    const pts = frames.map(f => {
      const x = xScale(f.t);
      const y = yScale(accessor(f));
      return `${Number.isFinite(y) ? y : H},${x}`;  // will reassemble below
    });
    const d = frames.map((f, i) => {
      const x = xScale(f.t);
      const y = yScale(accessor(f));
      const yc = Number.isFinite(y) ? Math.max(0, Math.min(H, y)) : H;
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${yc.toFixed(1)}`;
    }).join(' ');
    return <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />;
  };

  // Y-axis ticks (3 ticks)
  const yTicks = yScale.ticks(3);
  const xTicks = [0, Math.round(duration / 2), duration];

  const faultX = faultOnsetT != null ? xScale(faultOnsetT) : null;

  return (
    <div className="sandbox-chart">
      <div className="sandbox-chart-label">{label}</div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid */}
          {yTicks.map(v => (
            <line key={v} x1={0} x2={W} y1={yScale(v)} y2={yScale(v)}
              stroke="#1e2536" strokeWidth={1} />
          ))}

          {/* Fault onset marker */}
          {faultX != null && (
            <line x1={faultX} x2={faultX} y1={0} y2={H}
              stroke="#FF4444" strokeWidth={1} strokeDasharray="4,3" opacity={0.7} />
          )}

          {/* Series */}
          {buildPath(framesA, COLORS.A)}
          {buildPath(framesB, COLORS.B)}

          {/* Y axis ticks */}
          {yTicks.map(v => (
            <g key={v} transform={`translate(0,${yScale(v)})`}>
              <line x1={-4} x2={0} stroke="#475569" />
              <text x={-6} dy="0.35em" textAnchor="end"
                style={{ fontSize: 9, fill: '#64748B', fontFamily: 'var(--font-mono, monospace)' }}>
                {v.toFixed(typeof v === 'number' && Math.abs(v) < 10 ? 1 : 0)}{unit}
              </text>
            </g>
          ))}

          {/* X axis ticks */}
          {xTicks.map(v => (
            <g key={v} transform={`translate(${xScale(v)},${H})`}>
              <line y1={0} y2={4} stroke="#475569" />
              <text y={14} textAnchor="middle"
                style={{ fontSize: 9, fill: '#64748B', fontFamily: 'var(--font-mono, monospace)' }}>
                {v}s
              </text>
            </g>
          ))}

          {/* Border */}
          <rect x={0} y={0} width={W} height={H} fill="none" stroke="#1e2536" strokeWidth={1} />
        </g>
      </svg>
    </div>
  );
}
