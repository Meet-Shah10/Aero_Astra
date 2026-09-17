/**
 * SandboxConfig.jsx
 * ──────────────────
 * Left-panel parameter editor for the Simulation Sandbox.
 * Provides satellite presets, fault picker, severity/duration sliders,
 * playback speed selector, and Run / Stop / Compare buttons.
 */
import React, { useState } from 'react';

const FAULTS = [
  { id: null,                           label: 'None (Nominal)' },
  { id: 'tcs_thermal_runaway',          label: 'TCS Thermal Runaway' },
  { id: 'eps_cascade_power_failure',    label: 'EPS Power Cascade Failure' },
  { id: 'eps_battery_degradation',      label: 'EPS Battery Degradation' },
  { id: 'adcs_reaction_wheel_degradation', label: 'ADCS Wheel Degradation' },
  { id: 'adcs_sensor_fusion_failure',   label: 'ADCS Sensor Fusion Failure' },
  { id: 'ttc_signal_dropout',           label: 'TT&C Signal Dropout' },
  { id: 'propulsion_thruster_fault',    label: 'Propulsion Thruster Fault' },
];

const PRESETS = [
  {
    label: 'LEO Comms Sat',
    config: { battery_soc: 0.85, duration: 900,  dt: 5,  fault_onset_pct: 0.2, severity: 0.7 },
  },
  {
    label: 'Sun-Sync Earth Obs',
    config: { battery_soc: 0.90, duration: 1800, dt: 10, fault_onset_pct: 0.25, severity: 0.6 },
  },
  {
    label: 'GEO Weather Sat',
    config: { battery_soc: 0.95, duration: 3600, dt: 20, fault_onset_pct: 0.3,  severity: 0.8 },
  },
];

const SPEEDS = [
  { label: '1×',  value: 1 },
  { label: '5×',  value: 5 },
  { label: '10×', value: 10 },
  { label: 'MAX', value: 0 },
];

export default function SandboxConfig({ onStart, onStop, onCompare, status }) {
  const [fault,        setFault]       = useState(null);
  const [severity,     setSeverity]    = useState(0.7);
  const [duration,     setDuration]    = useState(900);
  const [dt,           setDt]          = useState(5);
  const [onsetPct,     setOnsetPct]    = useState(0.2);
  const [batterySoc,   setBatterySoc]  = useState(0.85);
  const [speed,        setSpeed]       = useState(1);
  const [compareMode,  setCompareMode] = useState(false);

  const buildConfig = () => ({
    fault,
    severity,
    duration,
    dt,
    fault_onset_pct: onsetPct,
    battery_soc: batterySoc,
    speed,
  });

  const applyPreset = (preset) => {
    const c = preset.config;
    if (c.battery_soc  !== undefined) setBatterySoc(c.battery_soc);
    if (c.duration     !== undefined) setDuration(c.duration);
    if (c.dt           !== undefined) setDt(c.dt);
    if (c.fault_onset_pct !== undefined) setOnsetPct(c.fault_onset_pct);
    if (c.severity     !== undefined) setSeverity(c.severity);
  };

  const running = status === 'running';

  return (
    <div className="sandbox-config">
      <div className="sandbox-config-title">CONFIGURATION</div>

      {/* Presets */}
      <div className="sandbox-section-label">SATELLITE PRESET</div>
      <div className="sandbox-presets">
        {PRESETS.map(p => (
          <button key={p.label} className="sandbox-preset-btn" onClick={() => applyPreset(p)}>
            {p.label}
          </button>
        ))}
      </div>

      {/* Fault */}
      <div className="sandbox-section-label">FAULT INJECTION</div>
      <select
        className="sandbox-select"
        value={fault ?? ''}
        onChange={e => setFault(e.target.value || null)}
        disabled={running}
      >
        {FAULTS.map(f => (
          <option key={f.id ?? 'none'} value={f.id ?? ''}>{f.label}</option>
        ))}
      </select>

      {fault && (
        <>
          <div className="sandbox-section-label">
            SEVERITY — <span className="sandbox-value">{severity.toFixed(2)}</span>
          </div>
          <input type="range" min={0.1} max={1.0} step={0.05}
            value={severity} onChange={e => setSeverity(Number(e.target.value))}
            className="sandbox-slider" disabled={running} />

          <div className="sandbox-section-label">
            FAULT ONSET — <span className="sandbox-value">{Math.round(onsetPct * 100)}% into run</span>
          </div>
          <input type="range" min={0.05} max={0.8} step={0.05}
            value={onsetPct} onChange={e => setOnsetPct(Number(e.target.value))}
            className="sandbox-slider" disabled={running} />
        </>
      )}

      {/* Duration */}
      <div className="sandbox-section-label">
        DURATION — <span className="sandbox-value">{duration}s</span>
      </div>
      <input type="range" min={120} max={7200} step={60}
        value={duration} onChange={e => setDuration(Number(e.target.value))}
        className="sandbox-slider" disabled={running} />

      {/* Initial SOC */}
      <div className="sandbox-section-label">
        INITIAL BATTERY SOC — <span className="sandbox-value">{Math.round(batterySoc * 100)}%</span>
      </div>
      <input type="range" min={0.1} max={1.0} step={0.05}
        value={batterySoc} onChange={e => setBatterySoc(Number(e.target.value))}
        className="sandbox-slider" disabled={running} />

      {/* Playback speed */}
      <div className="sandbox-section-label">PLAYBACK SPEED</div>
      <div className="sandbox-speed-row">
        {SPEEDS.map(s => (
          <button
            key={s.label}
            className={`sandbox-speed-btn ${speed === s.value ? 'active' : ''}`}
            onClick={() => setSpeed(s.value)}
            disabled={running}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Actions */}
      <div className="sandbox-actions">
        {!running ? (
          <button className="sandbox-btn sandbox-btn-run" onClick={() => onStart(buildConfig(), 'A')}>
            ▶ RUN
          </button>
        ) : (
          <button className="sandbox-btn sandbox-btn-stop" onClick={onStop}>
            ⏹ STOP
          </button>
        )}

        {!running && (
          <button
            className={`sandbox-btn sandbox-btn-compare ${compareMode ? 'active' : ''}`}
            onClick={() => {
              setCompareMode(c => !c);
              if (!compareMode) onCompare?.(buildConfig());
              else onCompare?.(null);
            }}
            title="Run a second scenario to compare side-by-side"
          >
            ⊞ COMPARE
          </button>
        )}
      </div>

      {compareMode && !running && (
        <div className="sandbox-compare-note">
          Compare mode active — Run A is locked. Adjust parameters for Run B, then press RUN.
          <br />
          <button className="sandbox-btn sandbox-btn-run" style={{ marginTop: 8 }}
            onClick={() => onStart(buildConfig(), 'B')}>
            ▶ RUN B
          </button>
        </div>
      )}

      <div className="sandbox-legend">
        <span className="sandbox-legend-dot" style={{ background: '#00E5A0' }} /> Run A
        {compareMode && <><span className="sandbox-legend-dot" style={{ background: '#FFA040', marginLeft: 12 }} /> Run B</>}
      </div>
    </div>
  );
}
