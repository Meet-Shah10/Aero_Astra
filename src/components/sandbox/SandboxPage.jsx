/**
 * SandboxPage.jsx
 * ─────────────────
 * Root component for the SIMULATION SANDBOX agent tab.
 *
 * Layout (3 columns):
 *   [Config Panel] | [Live Charts 2×3] | [3D Model + Vitals summary]
 *
 * Data flow:
 *   useSandboxWs  →  framesA/framesB arrays + latestA/latestB for 3D wiring
 *   SandboxConfig →  builds config object, calls startRun/stopRun
 *   SandboxChart  →  renders each subsystem time-series with d3 scales
 *   ModelViewer   →  receives sandboxState prop for 3D wiring
 */
import React, { useMemo } from 'react';
import './sandbox.css';
import SandboxConfig from './SandboxConfig.jsx';
import SandboxChart  from './SandboxChart.jsx';
import useSandboxWs  from './useSandboxWs.js';
import ModelViewer   from '../ModelViewer.jsx';

const MODEL_URL = '/simple_satellite_low_poly_free.glb';

// ── Summary card shown once simulation completes ──────────────────────────────
function FinalMetrics({ frames, label, color }) {
  if (!frames?.length) return null;
  const socs   = frames.map(f => f.subsystems?.EPS?.battery_soc ?? 1).filter(Number.isFinite);
  const temps  = frames.map(f => f.subsystems?.TCS?.panel_temp  ?? 0).filter(Number.isFinite);
  const errs   = frames.map(f => f.subsystems?.ADCS?.attitude_error ?? 0).filter(Number.isFinite);
  const minSoc  = socs.length  ? Math.min(...socs)  : null;
  const maxTemp = temps.length ? Math.max(...temps) : null;
  const maxErr  = errs.length  ? Math.max(...errs)  : null;

  const outcome = minSoc !== null
    ? minSoc < 0.05  ? 'MISSION LOSS'
    : minSoc < 0.40  ? 'DEGRADED'
    : 'NOMINAL'
    : '—';
  const outcomeColor = outcome === 'NOMINAL' ? '#00E5A0' : outcome === 'DEGRADED' ? '#FFA040' : '#FF4444';

  return (
    <div className="sandbox-metrics-card" style={{ borderColor: color }}>
      <div className="sandbox-metrics-run-label" style={{ color }}>RUN {label}</div>
      <div className="sandbox-metric-row">
        <span>Outcome</span>
        <span style={{ color: outcomeColor, fontWeight: 700 }}>{outcome}</span>
      </div>
      <div className="sandbox-metric-row">
        <span>Min SOC</span>
        <span>{minSoc !== null ? `${(minSoc * 100).toFixed(1)}%` : '—'}</span>
      </div>
      <div className="sandbox-metric-row">
        <span>Max Panel Temp</span>
        <span>{maxTemp !== null ? `${maxTemp.toFixed(1)}°C` : '—'}</span>
      </div>
      <div className="sandbox-metric-row">
        <span>Max Att. Error</span>
        <span>{maxErr !== null ? `${maxErr.toFixed(2)}°` : '—'}</span>
      </div>
    </div>
  );
}

// ── Health gauge (small circular) ─────────────────────────────────────────────
function HealthGauge({ label, value }) {
  const pct   = Math.max(0, Math.min(1, value ?? 1));
  const r     = 16;
  const circ  = 2 * Math.PI * r;
  const color = pct < 0.5 ? '#FF4444' : pct < 0.85 ? '#FFA040' : '#00E5A0';
  return (
    <div className="sandbox-health-gauge">
      <svg width={44} height={44} viewBox="0 0 44 44">
        <circle cx={22} cy={22} r={r} fill="none" stroke="#1e2536" strokeWidth={4} />
        <circle cx={22} cy={22} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={circ} strokeDashoffset={circ - pct * circ}
          transform="rotate(-90 22 22)" />
        <text x={22} y={26} textAnchor="middle"
          style={{ fontSize: 8, fill: color, fontFamily: 'var(--font-mono, monospace)', fontWeight: 700 }}>
          {Math.round(pct * 100)}%
        </text>
      </svg>
      <div className="sandbox-health-label">{label}</div>
    </div>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ progress, label, color }) {
  return (
    <div className="sandbox-progress">
      <div className="sandbox-progress-row">
        <span className="sandbox-progress-label">{label}</span>
        <span className="sandbox-progress-pct" style={{ color }}>{Math.round(progress * 100)}%</span>
      </div>
      <div className="sandbox-progress-track">
        <div className="sandbox-progress-fill" style={{ width: `${progress * 100}%`, background: color }} />
      </div>
    </div>
  );
}

// ── Main SandboxPage ──────────────────────────────────────────────────────────
export default function SandboxPage({ backendOnline }) {
  const { status, framesA, framesB, latestA, latestB, progress, startRun, stopRun } = useSandboxWs();

  const compareActive = framesB.length > 0;

  // Build sandboxState for ModelViewer 3D wiring
  // Priority: latestA (the primary run being watched)
  const sandboxState = useMemo(() => {
    const f = latestA;
    if (!f?.subsystems) return null;
    return {
      attitude_error:       f.subsystems.ADCS?.attitude_error ?? 0,
      reaction_wheel_speed: f.subsystems.ADCS?.reaction_wheel_speed ?? 1200,
      panel_temp:           f.subsystems.TCS?.panel_temp ?? 25,
      battery_soc:          f.subsystems.EPS?.battery_soc ?? 0.85,
      solar_array_current:  f.subsystems.EPS?.solar_array_current ?? 7.5,
      fault_active:         f.fault_active,
      fault_onset_t:        f.fault_onset_t,
      t:                    f.t,
    };
  }, [latestA]);

  const vitalsA = latestA?.vitals;
  const vitalsB = latestB?.vitals;

  const faultOnsetA = framesA.find(f => f.fault_active)?.t ?? null;
  const faultOnsetB = framesB.find(f => f.fault_active)?.t ?? null;
  const dur = framesA.length ? framesA[framesA.length - 1].t : 900;

  const handleCompare = (cfg) => {
    if (cfg) startRun(cfg, 'B');
  };

  const isDone = status === 'done';

  return (
    <div className="sandbox-root">
      {/* ── Left: Config ── */}
      <div className="sandbox-left">
        <SandboxConfig
          onStart={startRun}
          onStop={stopRun}
          onCompare={handleCompare}
          status={status}
        />

        {/* Status banner */}
        <div className={`sandbox-status-banner sandbox-status-${status}`}>
          {status === 'idle'    && 'Configure and press RUN to start.'}
          {status === 'running' && '● SIMULATING…'}
          {status === 'done'    && '✓ SIMULATION COMPLETE'}
          {status === 'stopped' && '⏹ STOPPED'}
          {status === 'error'   && '⚠ ERROR — backend offline?'}
        </div>

        {/* Progress bars */}
        {(status === 'running' || status === 'done') && (
          <div className="sandbox-progress-area">
            <ProgressBar progress={progress.A} label="Run A" color="#00E5A0" />
            {compareActive && <ProgressBar progress={progress.B} label="Run B" color="#FFA040" />}
          </div>
        )}

        {/* Final metrics */}
        {isDone && (
          <div className="sandbox-final-metrics">
            <FinalMetrics frames={framesA} label="A" color="#00E5A0" />
            {compareActive && <FinalMetrics frames={framesB} label="B" color="#FFA040" />}
          </div>
        )}
      </div>

      {/* ── Centre: Charts ── */}
      <div className="sandbox-centre">
        <div className="sandbox-charts-header">
          LIVE PHYSICS — {status === 'idle' ? 'Awaiting run…' : `t = ${latestA ? latestA.t.toFixed(0) : 0}s`}
          {latestA?.fault_active && (
            <span className="sandbox-fault-badge">⚡ {latestA.fault_active.replace(/_/g, ' ').toUpperCase()}</span>
          )}
        </div>
        <div className="sandbox-charts-grid">
          <SandboxChart label="Battery SOC" unit="%" framesA={framesA} framesB={framesB}
            accessor={f => (f.subsystems?.EPS?.battery_soc ?? 1) * 100}
            faultOnsetT={faultOnsetA} duration={dur} yMin={0} yMax={100} />
          <SandboxChart label="Panel Temp" unit="°C" framesA={framesA} framesB={framesB}
            accessor={f => f.subsystems?.TCS?.panel_temp ?? 25}
            faultOnsetT={faultOnsetA} duration={dur} />
          <SandboxChart label="Attitude Error" unit="°" framesA={framesA} framesB={framesB}
            accessor={f => Math.abs(f.subsystems?.ADCS?.attitude_error ?? 0)}
            faultOnsetT={faultOnsetA} duration={dur} yMin={0} />
          <SandboxChart label="Wheel Speed" unit=" RPM" framesA={framesA} framesB={framesB}
            accessor={f => f.subsystems?.ADCS?.reaction_wheel_speed ?? 1200}
            faultOnsetT={faultOnsetA} duration={dur} />
          <SandboxChart label="Signal Strength" unit=" dBm" framesA={framesA} framesB={framesB}
            accessor={f => f.subsystems?.TTC?.signal_strength ?? -75}
            faultOnsetT={faultOnsetA} duration={dur} />
          <SandboxChart label="Propellant Mass" unit=" kg" framesA={framesA} framesB={framesB}
            accessor={f => f.subsystems?.PROP?.fuel_remaining ?? 48}
            faultOnsetT={faultOnsetA} duration={dur} />
        </div>
      </div>

      {/* ── Right: 3D + vitals ── */}
      <div className="sandbox-right">
        <div className="sandbox-3d-label">3D STATE</div>
        {sandboxState && (
          <div className="sandbox-state-overlay">
            <span className="sandbox-state-row">
              Att. Error: <b>{sandboxState.attitude_error.toFixed(2)}°</b>
            </span>
            <span className="sandbox-state-row">
              Panel: <b style={{ color: sandboxState.panel_temp > 60 ? '#FF4444' : sandboxState.panel_temp > 49 ? '#FFA040' : '#00E5A0' }}>
                {sandboxState.panel_temp.toFixed(1)}°C
              </b>
            </span>
            <span className="sandbox-state-row">
              SOC: <b>{(sandboxState.battery_soc * 100).toFixed(1)}%</b>
            </span>
          </div>
        )}
        <ModelViewer
          url={MODEL_URL}
          width="100%"
          height={260}
          autoRotate={!sandboxState}
          autoRotateSpeed={0.3}
          enableMouseParallax={false}
          enableHoverRotation={false}
          enableManualRotation={true}
          showScreenshotButton={false}
          fadeIn={false}
          sandboxState={sandboxState}
          environmentPreset="night"
          ambientIntensity={0.2}
          keyLightIntensity={0.8}
        />

        {/* Vitals gauges */}
        <div className="sandbox-vitals-title">SUBSYSTEM HEALTH</div>
        {vitalsA ? (
          <div className="sandbox-health-grid">
            <HealthGauge label="EPS"  value={vitalsA.eps_health}  />
            <HealthGauge label="TCS"  value={vitalsA.tcs_health}  />
            <HealthGauge label="ADCS" value={vitalsA.adcs_health} />
            <HealthGauge label="TT&C" value={vitalsA.ttc_health}  />
          </div>
        ) : (
          <div className="sandbox-no-vitals">Run a simulation to see live health scores.</div>
        )}

        {/* Compare vitals */}
        {vitalsB && (
          <>
            <div className="sandbox-vitals-title" style={{ color: '#FFA040', marginTop: 8 }}>RUN B HEALTH</div>
            <div className="sandbox-health-grid">
              <HealthGauge label="EPS"  value={vitalsB.eps_health}  />
              <HealthGauge label="TCS"  value={vitalsB.tcs_health}  />
              <HealthGauge label="ADCS" value={vitalsB.adcs_health} />
              <HealthGauge label="TT&C" value={vitalsB.ttc_health}  />
            </div>
          </>
        )}

        {/* Offline note */}
        {!backendOnline && (
          <div className="sandbox-offline-note">
            ⚠ Backend offline — start backend/api.py to run simulations.
          </div>
        )}
      </div>
    </div>
  );
}
