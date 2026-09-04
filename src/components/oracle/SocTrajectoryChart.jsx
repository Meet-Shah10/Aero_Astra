/**
 * SocTrajectoryChart — Battery SOC trajectory chart.
 * Pure SVG implementation (no external chart library) using the D3-style
 * math we already have via native JS. D3 is available in this project but
 * we don't need to import it — a small custom SVG path renderer is sufficient
 * for a single line + band chart of this complexity.
 */
import React, { useMemo, useState } from 'react';

const W = 340;
const H = 200;
const PAD = { top: 10, right: 16, bottom: 36, left: 44 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

const COLORS = {
  meanLine:   '#10B981',
  band:       'rgba(16,185,129,0.12)',
  bandStroke: 'rgba(16,185,129,0.25)',
  grid:       '#1E2738',
  axis:       '#64748B',
};

// Map value → SVG coordinate
function scaleX(t, minT, maxT) {
  return PAD.left + ((t - minT) / (maxT - minT)) * INNER_W;
}
function scaleY(v) {
  // 0..100 → bottom..top
  return PAD.top + INNER_H - (v / 100) * INNER_H;
}

// Build a polyline "points" string from [{x,y}]
function toPoints(pts) {
  return pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
}

// Build closed SVG polygon for band (upper + reversed lower)
function toBandPath(hiPts, loPts) {
  const forward  = hiPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const backward = [...loPts].reverse().map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  return `M ${forward} L ${backward} Z`;
}

export default function SocTrajectoryChart({ trajectory, stdFinalSoc }) {
  const [tooltip, setTooltip] = useState(null);

  const { meanPts, hiPts, loPts, minT, maxT, yTicks, xTicks, finalPoint, insightStd, insightMean } = useMemo(() => {
    if (!trajectory?.length) return {};

    const data = trajectory.map(p => ({
      ...p,
      hi: Math.min(100, p.meanSoc + p.stdSoc),
      lo: Math.max(0,   p.meanSoc - p.stdSoc),
    }));

    const minT = data[0].timeMinutes;
    const maxT = data[data.length - 1].timeMinutes;

    const meanPts = data.map(p => ({ x: scaleX(p.timeMinutes, minT, maxT), y: scaleY(p.meanSoc), raw: p }));
    const hiPts   = data.map(p => ({ x: scaleX(p.timeMinutes, minT, maxT), y: scaleY(p.hi) }));
    const loPts   = data.map(p => ({ x: scaleX(p.timeMinutes, minT, maxT), y: scaleY(p.lo) }));

    // Y-axis ticks: 0, 25, 50, 75, 100
    const yTicks = [0, 25, 50, 75, 100];
    // X-axis ticks: evenly spaced 5 labels
    const step   = (maxT - minT) / 4;
    const xTicks = [0, 1, 2, 3, 4].map(i => minT + i * step);

    const finalPoint = data[data.length - 1];
    const insightStd  = stdFinalSoc?.toFixed(1) ?? finalPoint?.stdSoc?.toFixed(1) ?? '?';
    const insightMean = finalPoint?.meanSoc?.toFixed(0) ?? '?';

    return { meanPts, hiPts, loPts, minT, maxT, yTicks, xTicks, finalPoint, insightStd, insightMean };
  }, [trajectory, stdFinalSoc]);

  if (!trajectory?.length || !meanPts) {
    return (
      <div className="oracle-soc-card oracle-card">
        <div className="oracle-card-title">BATTERY SOC TRAJECTORY</div>
        <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#374151', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
          No trajectory data
        </div>
      </div>
    );
  }

  const bandPath = toBandPath(hiPts, loPts);

  return (
    <div className="oracle-soc-card oracle-card">
      <div className="oracle-card-title">BATTERY SOC TRAJECTORY (across runs)</div>
      <div style={{ fontSize: 9, color: '#64748B', fontFamily: 'var(--font-mono)', marginBottom: 10, letterSpacing: '0.05em' }}>
        Mean ± 1 Std Dev (100 runs)
      </div>

      {/* SVG chart */}
      <div style={{ position: 'relative', userSelect: 'none' }}>
        <svg
          width="100%"
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', overflow: 'visible' }}
          onMouseLeave={() => setTooltip(null)}
        >
          {/* Grid lines */}
          {yTicks.map(v => (
            <line
              key={v}
              x1={PAD.left} x2={W - PAD.right}
              y1={scaleY(v)} y2={scaleY(v)}
              stroke={COLORS.grid}
              strokeWidth={0.5}
              strokeDasharray="3 3"
            />
          ))}

          {/* Y-axis labels */}
          {yTicks.map(v => (
            <text
              key={v}
              x={PAD.left - 6}
              y={scaleY(v) + 3.5}
              textAnchor="end"
              fontSize={8}
              fontFamily="var(--font-mono)"
              fill={COLORS.axis}
            >
              {v}%
            </text>
          ))}

          {/* X-axis labels */}
          {xTicks.map(t => (
            <text
              key={t}
              x={scaleX(t, minT, maxT)}
              y={H - PAD.bottom + 14}
              textAnchor="middle"
              fontSize={8}
              fontFamily="var(--font-mono)"
              fill={COLORS.axis}
            >
              {Math.round(t)}m
            </text>
          ))}

          {/* Axis labels */}
          <text
            x={PAD.left - 34}
            y={PAD.top + INNER_H / 2}
            textAnchor="middle"
            fontSize={8}
            fontFamily="var(--font-mono)"
            fill={COLORS.axis}
            transform={`rotate(-90, ${PAD.left - 34}, ${PAD.top + INNER_H / 2})`}
          >
            SOC %
          </text>
          <text
            x={PAD.left + INNER_W / 2}
            y={H - 2}
            textAnchor="middle"
            fontSize={8}
            fontFamily="var(--font-mono)"
            fill={COLORS.axis}
          >
            Time (minutes)
          </text>

          {/* ±1σ band */}
          <path d={bandPath} fill={COLORS.band} stroke={COLORS.bandStroke} strokeWidth={0.8} />

          {/* Mean line */}
          <polyline
            points={toPoints(meanPts)}
            fill="none"
            stroke={COLORS.meanLine}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Hover hit areas */}
          {meanPts.map((pt, i) => (
            <circle
              key={i}
              cx={pt.x}
              cy={pt.y}
              r={5}
              fill="transparent"
              onMouseEnter={() => setTooltip({ x: pt.x, y: pt.y, raw: pt.raw })}
            />
          ))}

          {/* Tooltip dot */}
          {tooltip && (
            <circle cx={tooltip.x} cy={tooltip.y} r={4} fill={COLORS.meanLine} />
          )}
        </svg>

        {/* Floating tooltip */}
        {tooltip && (
          <div style={{
            position: 'absolute',
            left: tooltip.x / W * 100 + '%',
            top:  tooltip.y / H * 100 + '%',
            transform: 'translate(-50%, -120%)',
            background: '#0D121D',
            border: '1px solid #1E2738',
            borderRadius: 4,
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            zIndex: 10,
          }}>
            <div style={{ color: '#64748B', marginBottom: 3 }}>t = {tooltip.raw.timeMinutes} min</div>
            <div style={{ color: '#10B981' }}>Mean SOC: {tooltip.raw.meanSoc?.toFixed(1)}%</div>
            <div style={{ color: 'rgba(16,185,129,0.65)' }}>
              Band: {tooltip.raw.lo?.toFixed(1)}% – {tooltip.raw.hi?.toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 4, fontFamily: 'var(--font-mono)', fontSize: 9, color: '#64748B' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 16, height: 2, background: '#10B981', display: 'inline-block' }} />
          Mean SOC
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 16, height: 8, background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.3)', display: 'inline-block', borderRadius: 2 }} />
          ± 1 Std Dev
        </span>
      </div>

      {/* Insight line */}
      <div className="oracle-soc-insight" style={{ marginTop: 10 }}>
        <span style={{ color: '#F59E0B', fontSize: 13 }}>⚠</span>
        <span>
          High final SOC with a tight std dev band indicates consistent recovery across simulations.
          Mean final SOC: <strong style={{ color: 'rgba(255,255,255,0.75)' }}>{insightMean}%</strong>
          {' '}± <strong style={{ color: 'rgba(255,255,255,0.75)' }}>{insightStd}%</strong> (1σ).
        </span>
      </div>
    </div>
  );
}
