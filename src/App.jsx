import React, { useState, useEffect, useRef } from 'react';
import ModelViewer from './components/ModelViewer';
import Scene3D from './components/Scene3D';
import RotatingEarth from './components/RotatingEarth';
import PillNav from './components/PillNav';
import AgentNav from './components/AgentNav';
import AgentDetailPage from './components/AgentDetailPage';
import BorderGlow from './components/BorderGlow';
import TargetCursor from './components/TargetCursor';
import OrbitSatellite from './components/OrbitSatellite';
import { useGLTF } from '@react-three/drei';
import './index.css';

useGLTF.preload('/simple_satellite_low_poly_free.glb');


// ─────────────────────────────────────────────────────────────────────────────
//  Agent roster — plain-English descriptions sourced verbatim from pitch.md's
//  agent table. `status` reflects what's actually wired today (see
//  audit_findings.md / backend.md), not aspirational architecture — an About
//  page that overclaims is worse than one that's honest about what's live.
// ─────────────────────────────────────────────────────────────────────────────
const AGENT_ROSTER = [
  { code: 'SENTINEL', role: 'The Early Warning System', desc: 'Watches all telemetry 24/7 and knows when something starts to look wrong — before a human would notice.', status: 'wired' },
  { code: 'SHERLOCK', role: 'The Detective', desc: "When SENTINEL raises an alarm, SHERLOCK figures out why — tracing the problem back to its root cause through a physics-constrained causal graph.", status: 'wired' },
  { code: 'ORACLE', role: 'The Simulator', desc: 'Runs 100 independent Monte Carlo simulations of each candidate fix before anything executes — odds, not guesses.', status: 'wired' },
  { code: 'ATHENA', role: 'The Strategist', desc: "Using ORACLE's simulations, picks the best recovery plan and writes out every step, in order, with its reasoning.", status: 'wired' },
  { code: 'GUARDIAN', role: 'The Safety Gate', desc: 'Low-risk fixes auto-execute and log themselves. High-risk fixes wait for a human to press approve — nothing executes without it.', status: 'wired' },
  { code: 'QUARTERMASTER', role: 'The Logistics Manager', desc: 'Coordinates with ground stations and, if needed, shifts load to other satellites in the fleet.', status: 'planned' },
  { code: 'SCRIBE', role: 'The Accountant', desc: "Every decision, every step, every agent's reasoning gets written into an audit trail automatically.", status: 'planned' },
  { code: 'CHRONICLE', role: 'The Live Log', desc: 'A running event log of everything happening, in real time, as it happens.', status: 'wired' },
  { code: 'VITALS', role: 'The Proactive Monitor', desc: 'Tracks subsystem health scores and remaining-useful-life estimates so degradation is visible before it becomes an anomaly.', status: 'wired' },
];

// ─────────────────────────────────────────────────────────────────────────────
//  Fault scenario catalog — the 3 faults verified to produce a real, visible
//  signal within a demo-length simulator run (see audit_findings.md §3).
//  `baseline` / `live` share keys so this doubles as the exact shape the
//  WebSocket `telemetry` message will fill in once backend/api.py exists
//  (see backend.md §5) — swapping mock data for real data later is a
//  matter of replacing these objects with WS payloads, not restructuring UI.
// ─────────────────────────────────────────────────────────────────────────────
const FAULT_SCENARIOS = {
  thermal_runaway: {
    key: 'thermal_runaway',
    faultId: 'tcs_thermal_runaway',
    label: 'Thermal Runaway',
    subsystem: 'TCS',
    summary: 'Heat pipe failure — panel temperature climbs unbounded toward thermal limits.',
    rootCause: 'Heat Pipe Failure (TCS)',
    causalChain: ['TCS', 'ADCS', 'EPS'],
    liveOverride: { tcsTemp: '76.3°C (+4.2°C/hr)', cpuUsage: '58%', epsLoad: '44%' },
  },
  signal_dropout: {
    key: 'signal_dropout',
    faultId: 'ttc_signal_dropout',
    label: 'Signal Dropout',
    subsystem: 'TT&C',
    summary: 'Antenna/transponder fault drops signal below lock threshold.',
    rootCause: 'Antenna Fault (TT&C)',
    causalChain: ['TT&C', 'OBC'],
    liveOverride: { commLink: '-114.7 dBm (LOSS)', cpuUsage: '39%', epsLoad: '35%' },
  },
  thruster_fault: {
    key: 'thruster_fault',
    faultId: 'propulsion_thruster_fault',
    label: 'Thruster Fault',
    subsystem: 'Propulsion',
    summary: 'Thruster valve misfire generates uncontrolled torque and heat.',
    rootCause: 'Valve Misfire (Propulsion)',
    causalChain: ['Propulsion', 'ADCS', 'TCS'],
    liveOverride: { tcsTemp: '61.8°C (+9.1°C/hr)', cpuUsage: '81%', epsLoad: '68%' },
  },
  cascade_power_failure: {
    key: 'cascade_power_failure',
    faultId: 'eps_cascade_power_failure',
    label: 'Power Cascade Failure',
    subsystem: 'EPS',
    summary: 'Solar array loss drops output to zero — battery drains under full load with no recharge path.',
    rootCause: 'Solar Array Loss (EPS)',
    causalChain: ['EPS', 'TCS', 'ADCS', 'OBC', 'TT&C'],
    liveOverride: { epsLoad: '97%', tcsTemp: '31.4°C (falling)', cpuUsage: '74%' },
  },
};

// Historical case-study scenario, kept separate from FAULT_SCENARIOS so the
// picker can render it with distinct styling — this replays a documented
// real-world loss-of-mission, not a synthetic fault. Runs through the same
// backend pipeline via the same faultId; SENTINEL's Engine C (residual
// correlation) is the detector this scenario specifically exercises.
const CASE_STUDY_SCENARIO = {
  key: 'hitomi_case_study',
  faultId: 'adcs_sensor_fusion_failure',
  label: 'Sensor Fusion Failure',
  subsystem: 'ADCS',
  summary: 'IRU vs. star-tracker disagreement drives wheel torque against a rotation that never happened.',
  rootCause: 'Sensor Fusion Disagreement (ADCS)',
  causalChain: ['ADCS', 'EPS'],
  liveOverride: { cpuUsage: '52%', epsLoad: '58%' },
  isCaseStudy: true,
  citation: {
    incident: 'JAXA Hitomi / ASTRO-H (2016)',
    source: '"Fatal Software Failures in Spaceflight," MDPI Encyclopedia (2024), DOI 10.3390/encyclopedia4020061',
    note: 'The satellite broke apart 38 days after launch after its attitude control system misjudged a false rotation, commanded reaction wheels to counter it, and failed to unload the resulting momentum in time.',
  },
};

const ALL_SCENARIOS = { ...FAULT_SCENARIOS, [CASE_STUDY_SCENARIO.key]: CASE_STUDY_SCENARIO };

const BASELINE_TELEMETRY = {
  altitude: '540 km | 7.5 km/s',
  epsLoad: '32%',
  cpuUsage: '14%',
  commLink: 'Stable',
  tcsTemp: 'Nominal',
};

const TELEMETRY_ROWS = [
  { key: 'altitude', label: 'Altitude / Velocity' },
  { key: 'epsLoad', label: 'EPS Load' },
  { key: 'cpuUsage', label: 'CPU Usage' },
  { key: 'commLink', label: 'Comm-Link' },
  { key: 'tcsTemp', label: 'TCS Temp' },
];

// Severity below this auto-executes (AUTOMATED_GUARDED); at/above it, GUARDIAN
// requires a human approval click (MANUAL_INTERLOCK). See roadmap.md's MVP
// section — this is the branch that produces the demo's two real outcomes.
const HIGH_RISK_SEVERITY_THRESHOLD = 0.7;

// Right-sidebar mission timeline — replaces the old per-agent detail panels
// (VITALS/SHERLOCK/ATHENA), which now live exclusively behind the AgentNav
// console so they're not duplicated in two places. minPhaseIdx into
// PHASE_ORDER decides when each stage lights up; ORACLE and ATHENA share an
// index since both are conceptually active during 'planning'.
const PHASE_ORDER = ['detected', 'diagnosing', 'planning', 'awaiting_approval', 'executing', 'resolved'];
const MISSION_STAGES = [
  { code: 'SENTINEL', minPhaseIdx: 0 },
  { code: 'SHERLOCK', minPhaseIdx: 1 },
  { code: 'ORACLE', minPhaseIdx: 2 },
  { code: 'ATHENA', minPhaseIdx: 2 },
  { code: 'GUARDIAN', minPhaseIdx: 3 },
  { code: 'SCRIBE', minPhaseIdx: 4 },
];

// ─────────────────────────────────────────────────────────────────────────────
//  Web Audio Beep
// ─────────────────────────────────────────────────────────────────────────────
const playBeep = () => {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(820, ctx.currentTime);
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.12);
  } catch (e) { }
};

// ─────────────────────────────────────────────────────────────────────────────
//  Live UTC Clock
// ─────────────────────────────────────────────────────────────────────────────
function LiveClock() {
  const [time, setTime] = useState('00:00:00');
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const h = String(now.getUTCHours()).padStart(2, '0');
      const m = String(now.getUTCMinutes()).padStart(2, '0');
      const s = String(now.getUTCSeconds()).padStart(2, '0');
      setTime(`${h}:${m}:${s}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span>{time}</span>;
}

// ─────────────────────────────────────────────────────────────────────────────
//  MET Timer
// ─────────────────────────────────────────────────────────────────────────────
function MetTimer({ start }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [start]);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  return <span>MET {h}:{m}:{s}</span>;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Dashboard System Meter
// ─────────────────────────────────────────────────────────────────────────────
function SystemMeter({ label }) {
  const [val, setVal] = useState(60);
  useEffect(() => {
    const update = () => setVal(40 + Math.floor(Math.random() * 50));
    update();
    const id = setInterval(update, 3000);
    return () => clearInterval(id);
  }, []);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ fontSize: '8px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.15em', fontWeight: 'bold', textTransform: 'uppercase' }}>{label}</span>
      <div style={{ width: '40px', height: '3px', background: 'rgba(255,255,255,0.05)', borderRadius: '99px', overflow: 'hidden' }}>
        <div style={{ width: `${val}%`, height: '100%', background: '#EDEEF2', transition: 'width 0.8s ease' }} />
      </div>
      <span style={{ fontSize: '9px', color: 'rgba(230,232,236,0.85)', fontFamily: 'monospace', minWidth: '28px', textAlign: 'right' }}>{val}%</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
//  About / Agents page — second Dock destination
// ─────────────────────────────────────────────────────────────────────────────
function AboutView() {
  return (
    <div className="about-view fade-enter">
      <div className="about-header">
        <div className="about-eyebrow">MULTI-AGENT ARCHITECTURE</div>
        <h2 className="about-title">Nine agents, one pipeline</h2>
        <p className="about-lede">
          Each agent has one job and hands off to the next — detection, diagnosis, simulation,
          decision, and a safety gate that decides whether a human needs to be in the loop.
        </p>
      </div>

      <div className="about-grid">
        {AGENT_ROSTER.map(agent => (
          <BorderGlow key={agent.code} borderRadius={8} glowRadius={22} fillOpacity={0.22} className="about-card-glow">
            <div className="about-card">
              <div className="about-card-top">
                <span className="about-card-code">{agent.code}</span>
                <span className={`about-card-status about-card-status--${agent.status}`}>
                  {agent.status === 'wired' ? '● LIVE' : '○ PLANNED'}
                </span>
              </div>
              <div className="about-card-role">{agent.role}</div>
              <p className="about-card-desc">{agent.desc}</p>
            </div>
          </BorderGlow>
        ))}
      </div>

      <div className="about-footnote">
        LIVE agents run against the real physics digital twin during the demo. PLANNED agents are
        represented as mocked panels on the dashboard until wired — see backend.md for build status.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
//  Main App
// ─────────────────────────────────────────────────────────────────────────────
function App() {
  // view states matching orbital-tomb flow:
  // 'hero' = landing page with globe
  // 'loading' = launched, camera dollying in, loading panel showing
  // 'dashboard' = full mission control
  const [launched, setLaunched] = useState(false);
  const [showLoader, setShowLoader] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const [loadStep, setLoadStep] = useState(0);
  const [missionStart, setMissionStart] = useState(null);

  // Dashboard states
  const [scenarioPhase, setScenarioPhase] = useState('nominal');
  const [guardianApproved, setGuardianApproved] = useState(false);
  const [selectedMitigation, setSelectedMitigation] = useState(1);
  const [logs, setLogs] = useState([
    '> System booted successfully.',
    '> Telemetry linked on band S7.',
    '> SENTINEL: Monitoring 5 active assets.',
  ]);

  // Which top-level page is active — PillNav switches between these two.
  // No third "Missions" page: out of scope for the problem statement.
  const [activeView, setActiveView] = useState('dashboard');

  // Which agent's drill-down page is showing in the dashboard's main content
  // area. null = the normal operational grid (3D view + bottom-bar controls).
  const [activeAgentPage, setActiveAgentPage] = useState(null);

  // Scenario picker + comparison panel state
  const [showScenarioPicker, setShowScenarioPicker] = useState(false);
  const [pendingScenario, setPendingScenario] = useState('thermal_runaway');
  const [pendingSeverity, setPendingSeverity] = useState(0.7);
  const [activeScenario, setActiveScenario] = useState(null);
  const [activeSeverity, setActiveSeverity] = useState(null);
  const [guardianTier, setGuardianTier] = useState(null); // 'AUTOMATED_GUARDED' | 'MANUAL_INTERLOCK'
  const [showDiff, setShowDiff] = useState(false);

  // ── Real backend WebSocket state ──
  // wsRef keeps one persistent connection open while the dashboard is visible.
  // backendData holds the latest messages from each agent as they arrive.
  const wsRef = useRef(null);
  // executeRunbook() is called from inside the WebSocket onmessage closure
  // (AUTOMATED_GUARDED / AUTONOMOUS_SAFED auto-execute paths), which is
  // created once when the dashboard mounts and would otherwise always see
  // activeScenario as it was at that moment (null) — a stale closure. This
  // ref is kept in sync on every launch/reset so the WS-driven auto-execute
  // path always reads the real current scenario.
  const activeScenarioRef = useRef(null);
  // Tracks the last worst_health seen so CHRONICLE can log the exact moment
  // it crosses the SENTINEL fallback threshold (0.85), not just repeat the
  // sentinel_alert line — a real threshold-cross event, not a duplicate.
  const lastWorstHealthRef = useRef(1.0);
  const [backendOnline, setBackendOnline] = useState(false);
  const [backendData, setBackendData] = useState({
    sentinel: null,    // { triggered_engine, timestamp }
    sherlock: null,    // { primary_root_cause, causal_chain, urgency, confidence_score, time_to_critical }
    oracle: null,      // { best_action, top_score, mode }
    athena: null,      // { recommended_action, rationale }
    guardian: null,    // { status, action_taken }
    telemetry: null,   // { subsystems: { ADCS, EPS } }
    vitals: null,      // { worst_health, ... }
  });

  const loadMessages = [
    '> BOOT: AERO-ASTRA MISSION CONTROL v2.5',
    '> SENTINEL: Initializing anomaly detection engine...',
    '> SHERLOCK: Loading causal dependency graph...',
    '> ATHENA: Recovery plan modules standing by...',
    '> ORACLE: Digital twin sync established...',
    '> GUARDIAN: Safety gate armed and nominal...',
    '> SCRIBE: Audit trail ready. All agents online.',
  ];

  // ── WebSocket connection: open immediately on mount, persist for session ──
  useEffect(() => {
    const WS_URL = 'ws://localhost:8000/ws';
    let ws;
    let reconnectTimer;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setBackendOnline(true);
        setLogs(prev => [...prev, '> BACKEND: WebSocket connected — real telemetry streaming.']);
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          switch (msg.type) {
            case 'telemetry':
              setBackendData(prev => ({ ...prev, telemetry: msg }));
              break;
            case 'vitals_update': {
              setBackendData(prev => ({ ...prev, vitals: msg.payload }));
              const worst = msg.payload?.worst_health;
              const prevWorst = lastWorstHealthRef.current;
              if (typeof worst === 'number') {
                if (prevWorst >= 0.85 && worst < 0.85) {
                  const subsystem = ['eps_health', 'tcs_health', 'adcs_health', 'ttc_health']
                    .reduce((a, b) => (msg.payload[a] ?? 1) <= (msg.payload[b] ?? 1) ? a : b)
                    .replace('_health', '').toUpperCase();
                  setLogs(prev => [...prev,
                    `> ⚠ VITALS: ${subsystem} health crossed below warning threshold (${(worst * 100).toFixed(0)}%).`,
                  ]);
                } else if (prevWorst < 0.85 && worst >= 0.85) {
                  setLogs(prev => [...prev, `> VITALS: All subsystems back above threshold (worst ${(worst * 100).toFixed(0)}%).`]);
                }
                lastWorstHealthRef.current = worst;
              }
              break;
            }
            case 'sentinel_alert':
              setBackendData(prev => ({ ...prev, sentinel: msg }));
              setScenarioPhase('detected');
              setLogs(prev => [...prev,
                `> ⚠ SENTINEL: Anomaly detected via ${msg.triggered_engine}`,
              ]);
              break;
            case 'residual_update':
              setBackendData(prev => {
                const history = [...(prev.residualHistory || []), msg].slice(-120);
                return { ...prev, residualHistory: history };
              });
              break;
            case 'sherlock_diagnosis':
              setBackendData(prev => ({ ...prev, sherlock: msg }));
              setScenarioPhase(p => (p === 'detected' || p === 'nominal') ? 'diagnosing' : p);
              setLogs(prev => [...prev,
                `> SHERLOCK: Root cause → ${msg.primary_root_cause}`,
                `> SHERLOCK: Urgency ${msg.urgency}, TTC ${msg.time_to_critical}min`,
              ]);
              break;
            case 'oracle_simulation':
              setBackendData(prev => ({ ...prev, oracle: msg }));
              setScenarioPhase(p => (p === 'diagnosing' || p === 'detected') ? 'planning' : p);
              setLogs(prev => [...prev,
                `> ORACLE: Best action → ${msg.best_action} (score ${msg.top_score?.toFixed(2)})`,
              ]);
              break;
            case 'athena_plan':
              setBackendData(prev => ({ ...prev, athena: msg }));
              setLogs(prev => [...prev,
                `> ATHENA: Plan → ${msg.recommended_action}`,
              ]);
              break;
            case 'guardian_action':
              setBackendData(prev => ({ ...prev, guardian: msg }));
              setGuardianTier(msg.status);
              if (msg.status === 'AUTOMATED_GUARDED') {
                setGuardianApproved(true);
                setScenarioPhase('awaiting_approval');
                setLogs(prev => [...prev, '> GUARDIAN: AUTOMATED_GUARDED — executing recovery.']);
                setTimeout(() => executeRunbook(activeScenarioRef.current), 900);
              } else if (msg.status === 'MANUAL_INTERLOCK') {
                setScenarioPhase('awaiting_approval');
                setLogs(prev => [...prev, '> GUARDIAN: MANUAL_INTERLOCK — awaiting human approval.']);
              } else if (msg.status === 'AUTONOMOUS_SAFED') {
                setGuardianApproved(true);
                setScenarioPhase('awaiting_approval');
                setLogs(prev => [...prev, '> GUARDIAN: AUTONOMOUS_SAFED — critical threshold crossed, acting immediately.']);
                setTimeout(() => executeRunbook(activeScenarioRef.current), 300);
              }
              break;
            default:
              break;
          }
        } catch (_) {}
      };

      ws.onclose = () => {
        setBackendOnline(false);
        // Auto-reconnect after 3s
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        setBackendOnline(false);
        ws.close();
      };
    };

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Launch sequence ──
  // 1. Set launched=true → Scene3D camera starts dollying in
  // 2. After 800ms show the loader panel
  // 3. After 3000ms total → show dashboard
  const handleLaunch = () => {
    playBeep();
    setLaunched(true);

    // After camera starts moving, show loading overlay
    setTimeout(() => {
      setShowLoader(true);
      setLoadStep(0);
      // Stagger load messages
      loadMessages.forEach((_, i) => {
        setTimeout(() => setLoadStep(i + 1), i * 260);
      });
    }, 800);

    // Transition to dashboard
    setTimeout(() => {
      setShowDashboard(true);
      setMissionStart(Date.now());
    }, 3200);
  };

  // ── Dashboard scenario ──
  const resetSystem = () => {
    setScenarioPhase('nominal');
    setGuardianApproved(false);
    setSelectedMitigation(1);
    setActiveScenario(null);
    activeScenarioRef.current = null;
    lastWorstHealthRef.current = 1.0;
    setActiveSeverity(null);
    setGuardianTier(null);
    setShowDiff(false);
    setLogs(['> System reset.', '> Telemetry linked on band S7.', '> SENTINEL: Monitoring 5 active assets.']);
  };

  const openScenarioPicker = () => {
    if (scenarioPhase !== 'nominal' && scenarioPhase !== 'resolved') {
      resetSystem();
      return;
    }
    setShowScenarioPicker(true);
  };

  // Launches the chosen scenario — calls real backend POST /trigger,
  // then state is driven by incoming WebSocket messages above.
  // The mock liveOverride still fills in for telemetry fields not yet streamed.
  const launchScenario = () => {
    const scenario = ALL_SCENARIOS[pendingScenario];
    const severity = pendingSeverity;

    setShowScenarioPicker(false);
    setActiveScenario(scenario);
    activeScenarioRef.current = scenario;
    lastWorstHealthRef.current = 1.0;
    setActiveSeverity(severity);
    setShowDiff(false);
    // Reset agent data from the last run but KEEP residualHistory so the
    // Sentinel chart doesn't go blank during the ~20-frame window before new
    // residual_update messages arrive from the freshly-started stream.
    setBackendData(prev => ({ sentinel: null, sherlock: null, oracle: null, athena: null, guardian: null, telemetry: null, vitals: null, residualHistory: prev.residualHistory ?? [] }));
    setScenarioPhase('nominal');
    setGuardianTier(null);
    setGuardianApproved(false);

    // Call real backend — kicks off the physics simulation + full agent pipeline.
    // Falls back silently if backend is offline (keeps the UI usable in demo mode).
    fetch('http://localhost:8000/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault_name: scenario.faultId, severity }),
    }).then(r => r.json()).then(data => {
      setLogs(prev => [...prev,
        `> BACKEND: Scenario "${scenario.label}" injected (severity ${severity.toFixed(2)}).`,
        '> SENTINEL: Starting physics simulation + anomaly scoring...',
      ]);
    }).catch(() => {
      // Backend offline — fall back to the original mock timer cascade
      setLogs(prev => [...prev,
        '> ⚠ BACKEND OFFLINE: Running in mock mode (no real pipeline).',
        `> ⚠ WARN: Anomaly detected at ${scenario.subsystem}.`,
      ]);
      setScenarioPhase('detected');
      setTimeout(() => {
        setScenarioPhase('diagnosing');
        setLogs(prev => [...prev,
          '> SHERLOCK: Building causal dependency graph...',
          `> SHERLOCK: Root cause isolated → ${scenario.causalChain.join(' → ')}.`,
        ]);
        setTimeout(() => {
          setScenarioPhase('planning');
          setLogs(prev => [...prev, '> ATHENA: Generating recovery options.']);
          setTimeout(() => {
            const isHighRisk = severity >= HIGH_RISK_SEVERITY_THRESHOLD;
            if (isHighRisk) {
              setGuardianTier('MANUAL_INTERLOCK');
              setScenarioPhase('awaiting_approval');
              setLogs(prev => [...prev, '> GUARDIAN: HIGH severity → MANUAL_INTERLOCK.']);
            } else {
              setGuardianTier('AUTOMATED_GUARDED');
              setGuardianApproved(true);
              setScenarioPhase('awaiting_approval');
              setLogs(prev => [...prev, '> GUARDIAN: AUTOMATED_GUARDED — executing.']);
              setTimeout(() => executeRunbook(scenario), 900);
            }
          }, 3000);
        }, 3000);
      }, 3000);
    });
  };

  const handleApprove = (e) => {
    setGuardianApproved(e.target.checked);
    if (e.target.checked) setLogs(prev => [...prev, '> GUARDIAN: Safety Approval Granted.']);
    else setLogs(prev => [...prev, '> GUARDIAN: Approval Revoked.']);
  };

  const executeRunbook = (scenarioOverride) => {
    // Fall back to a generic placeholder rather than crashing — this can be
    // reached from the WebSocket auto-execute path where no local scenario
    // was ever set locally (e.g. backend fires a real alert independent of
    // the frontend's own picker flow).
    const scenario = scenarioOverride || activeScenario || {
      label: 'Detected Anomaly', faultId: 'unknown', subsystem: 'affected subsystem',
      rootCause: 'unknown', causalChain: ['unknown'],
    };
    setScenarioPhase('executing');
    setLogs(prev => [...prev,
    `> SCRIBE: Executing Option ${selectedMitigation}.`,
    selectedMitigation === 1 ? `> SCRIBE: Throttling ${scenario.subsystem} to safe limits...` : '> SCRIBE: Initiating Emergency Shutoff...',
      '> SCRIBE: Generating audit runbook.'
    ]);
    setTimeout(() => {
      setScenarioPhase('resolved');
      setLogs(prev => [...prev, '> SYSTEM: Telemetry nominal.', '> SCRIBE: Runbook finalized. Returning to monitoring.']);
      setGuardianApproved(false);
    }, 4000);
  };

  const isAnomaly = scenarioPhase !== 'nominal' && scenarioPhase !== 'resolved';

  // Live telemetry for the sidebar TELEMETRY_ROWS display.
  // Priority:
  //   1. Real backend WS telemetry (backendData.telemetry) when backend is online
  //      — converts raw numeric values to the display-string format the rows expect.
  //   2. liveOverride mock strings from FAULT_SCENARIOS when backend is offline.
  //   3. BASELINE_TELEMETRY as the no-fault baseline.
  const _wsTm = backendOnline ? backendData?.telemetry : null;
  const _realTelemetry = _wsTm ? {
    altitude: '540 km | 7.5 km/s',  // orbit is not in the WS payload, keep static
    epsLoad: `${(_wsTm.subsystems.EPS.battery_soc * 100).toFixed(1)}% SOC · ${_wsTm.subsystems.EPS.bus_voltage.toFixed(1)}V`,
    cpuUsage: BASELINE_TELEMETRY.cpuUsage,  // OBC cpu not in WS subset, keep baseline
    commLink: BASELINE_TELEMETRY.commLink,  // TTC not in WS subset, keep baseline
    tcsTemp: BASELINE_TELEMETRY.tcsTemp,   // TCS not in WS subset, keep baseline
  } : null;
  const liveTelemetry = _realTelemetry
    ? { ...BASELINE_TELEMETRY, ..._realTelemetry, ...(isAnomaly ? activeScenario?.liveOverride : null) }
    : { ...BASELINE_TELEMETRY, ...(isAnomaly ? activeScenario?.liveOverride : null) };

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden' }}>

      {/* ── Scan lines always present ── */}
      <div className="scan-lines" />

      {/* ── Nebula BG ── */}
      <div className="nebula-bg" />

      {/* ── Rotating Earth Background ── */}
      <div style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1,
        background: '#05060F',
        transform: `scale(${showDashboard ? 1.15 : launched ? 1.875 : 1})`,
        transition: 'transform 1.5s cubic-bezier(0.165, 0.84, 0.44, 1)',
        pointerEvents: launched ? 'none' : 'auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <RotatingEarth width={window.innerWidth} height={window.innerHeight} isRotating={!showDashboard} />
      </div>

      {/* Satellite orbiting around the globe — only on landing page, separate overlay */}
      {!launched && (
        <div style={{
          position: 'fixed',
          inset: 0,
          zIndex: 2,
          pointerEvents: 'none',
        }}>
          <OrbitSatellite count={1} radiusX={340} radiusY={100} rotation={-12} duration={18} itemSize={44} />
        </div>
      )}

      {/* ══════════════════════════════════════════════════════
          THREE.JS SCENE: Always mounted, camera dollies on launch
          (same as orbital-tomb — persistent z-0 background)
         ══════════════════════════════════════════════════════ */}
      <Scene3D launched={launched} dashboard={showDashboard} />

      {/* ── Blueprint grid overlay (appears after launch, matches orbital-tomb) ── */}
      {launched && (
        <div
          style={{
            position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 10, opacity: 0.7,
            backgroundImage: `
              linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px)
            `,
            backgroundSize: '60px 60px',
            maskImage: 'radial-gradient(circle at center, rgba(0,0,0,1) 35%, rgba(0,0,0,0) 85%)',
            WebkitMaskImage: 'radial-gradient(circle at center, rgba(0,0,0,1) 35%, rgba(0,0,0,0) 85%)',
          }}
        />
      )}

      {/* ── Vignette ── */}
      <div style={{
        position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 40,
        background: 'radial-gradient(circle, transparent 50%, rgba(0,0,0,0.35) 100%)',
      }} />

      {/* ════════════════════════════════════════════
          HEADER  — matches orbital-tomb exactly
         ════════════════════════════════════════════ */}
      {showDashboard ? (
        /* Dashboard header */
        <header style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 40,
          background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          display: 'flex', flexDirection: 'column',
        }}>
          {/* Row 1 */}
          <div style={{
            height: '56px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 32px', borderBottom: '1px solid rgba(255,255,255,0.05)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#EDEEF2" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" />
                <polygon points="12,6 6,16 18,16" strokeLinejoin="round" />
              </svg>
              <span className="font-bold" style={{ letterSpacing: '0.3em', fontSize: '15px', color: '#fff' }}>AERO-ASTRA</span>
            </div>

            <PillNav
              activeId={activeView}
              items={[
                { id: 'dashboard', label: 'Dashboard', onClick: () => { setActiveView('dashboard'); setActiveAgentPage(null); } },
                { id: 'about', label: 'About', onClick: () => setActiveView('about') },
              ]}
            />

          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '8px', letterSpacing: '0.15em', color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', fontWeight: 'bold' }}>UTC TIME</div>
              <div style={{ fontFamily: 'monospace', fontSize: '13px', fontWeight: 'bold', color: '#EDEEF2', letterSpacing: '0.1em' }}><LiveClock /></div>
            </div>
          </div>
        </div>

          {/* Row 2 — breadcrumb + MET */}
      <div style={{
        height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 32px', background: 'rgba(0,0,0,0.2)',
      }}>
        <div style={{ fontSize: '9px', fontFamily: 'monospace', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase' }}>
          MISSION CONTROL / {activeView === 'about' ? 'ABOUT' : 'DASHBOARD'} / <span style={{ color: '#EDEEF2', fontWeight: 'bold' }}>{activeView === 'about' ? 'AGENT ARCHITECTURE' : 'ANOMALY RESPONSE'}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: '#00FF88', fontFamily: 'monospace', fontWeight: 'bold' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00FF88', display: 'inline-block', animation: 'blink-dots 1.5s infinite' }} />
          {missionStart && <MetTimer start={missionStart} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '9px', color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace' }}>
          SIGNAL: <span style={{ color: '#00FF88', fontWeight: 'bold' }}>LINK_NOMINAL</span>
          &nbsp;|&nbsp;
          BACKEND: <span style={{ color: backendOnline ? '#00FF88' : '#ff4444', fontWeight: 'bold' }}>
            {backendOnline ? '● LIVE' : '○ OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  ) : (
    /* Landing / Loader header — exactly matching orbital-tomb */
    <header style={{
      position: 'fixed', top: 0, left: 0, right: 0, height: '64px', zIndex: 40,
      background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(8px)',
      borderBottom: '1px solid rgba(255,255,255,0.07)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#EDEEF2" strokeWidth="1.5">
          <circle cx="12" cy="12" r="10" />
          <polygon points="12,6 6,16 18,16" strokeLinejoin="round" />
        </svg>
        <span style={{ fontSize: '10px', letterSpacing: '0.25em', color: 'rgba(255,255,255,0.4)', fontWeight: 'bold', textTransform: 'uppercase' }}>
          SEC_LEVEL // 04
        </span>
      </div>

      <h1 style={{ margin: 0, fontSize: 'clamp(14px,1.5vw,18px)', letterSpacing: '0.3em', fontWeight: 'bold', color: '#fff' }}>
        AERO-ASTRA
      </h1>

      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: '8px', letterSpacing: '0.15em', color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', fontWeight: 'bold' }}>
          COORDINATED UNIVERSAL TIME
        </div>
        <div style={{ fontFamily: 'monospace', fontSize: '14px', fontWeight: 'bold', color: '#EDEEF2', letterSpacing: '0.1em' }}>
          <LiveClock />
        </div>
      </div>
    </header>
  )
}

{/* ════════════════════════════════════════════
          VIEW 1 — HERO (landing, globe visible behind)
         ════════════════════════════════════════════ */}
{
  !launched && (
    <main className="landing-main" style={{ zIndex: 20 }}>
      <div className="hero-tag">AUTONOMOUS SATELLITE MISSION OPS</div>

      <h2 className="hero-title">AERO-ASTRA</h2>

      <p className="hero-sub">Intelligent multi-agent AI for autonomous anomaly response.</p>

      <div className="hero-status">
        TELEMETRY SYNCED &middot; MULTI-AGENT ACTIVE &middot; OPSSAT-AD LIVE
      </div>

      <BorderGlow borderRadius={4} glowRadius={26} fillOpacity={0.25} className="launch-btn-glow">
        <button className="launch-btn cursor-target" onClick={handleLaunch} id="launch-mission-control">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="22" y1="12" x2="18" y2="12" />
            <line x1="6" y1="12" x2="2" y2="12" />
            <line x1="12" y1="6" x2="12" y2="2" />
            <line x1="12" y1="22" x2="12" y2="18" />
          </svg>
          LAUNCH MISSION CONTROL
        </button>
      </BorderGlow>
      
      <TargetCursor targetSelector=".cursor-target" cursorColor="#EDEEF2" cursorColorOnTarget="#00FF88" spinDuration={2} />

      {/* Coordinate corner decoration */}
      <div style={{
        position: 'absolute', bottom: '2rem', left: '2.5rem',
        fontFamily: 'monospace', fontSize: '8px', color: 'rgba(255,255,255,0.2)',
        letterSpacing: '0.15em', lineHeight: 1.8,
      }}>
        <div>LAT: 28.6139° N</div>
        <div>LON: 77.2090° E</div>
        <div>ALT: 540 KM</div>
      </div>
    </main>
  )
}

{/* ════════════════════════════════════════════
          VIEW 2 — LOADER PANEL
          (shown while camera dollies in, sat GLB pops)
         ════════════════════════════════════════════ */}
{
  launched && !showDashboard && showLoader && (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 30,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {/* No foreground model here — the persistent Scene3D globe (already
          dollying in behind everything) is the visual during this phase. */}

      {/* Loading panel at bottom */}
      <div style={{
        position: 'absolute', bottom: '3rem', left: '50%', transform: 'translateX(-50%)',
        width: '100%', maxWidth: '540px', zIndex: 10,
      }}>
        <div className="transition-panel">
          {/* Spinner */}
          <div style={{ position: 'relative', width: '48px', height: '48px', margin: '0 auto 20px' }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.05)' }} />
            <div className="spin-ring" />
          </div>

          <div style={{ fontSize: '10px', letterSpacing: '0.3em', color: '#EDEEF2', textTransform: 'uppercase', fontWeight: 'bold', marginBottom: '6px' }}>
            INITIALIZING MISSION CONTROL...
          </div>
          <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginBottom: '16px' }}>
            Multi-agent anomaly response system coming online
          </div>

          {/* Sequential log messages */}
          <div className="transition-log">
            {loadMessages.slice(0, loadStep).map((msg, i) => (
              <div key={i} style={{
                color: i === loadStep - 1 ? '#EDEEF2' : 'rgba(230,232,236,0.4)',
                marginBottom: '3px', fontSize: '10px', fontFamily: 'monospace', letterSpacing: '0.08em',
              }}>
                {i < loadStep - 1 && <span style={{ color: '#00FF88', marginRight: '4px' }}>✓</span>}
                {i === loadStep - 1 && <span style={{ color: '#EDEEF2', marginRight: '4px' }} className="dot-blink">▸</span>}
                {msg}
              </div>
            ))}
          </div>

          {/* Progress bar */}
          <div style={{ width: '100%', height: '2px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px', marginTop: '14px', overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${(loadStep / loadMessages.length) * 100}%`,
              background: 'linear-gradient(90deg, #EDEEF2, #00FF88)',
              transition: 'width 0.4s ease',
              boxShadow: '0 0 8px rgba(230,232,236,0.5)',
            }} />
          </div>
        </div>
      </div>
    </div>
  )
}

{/* ════════════════════════════════════════════
          VIEW 3 — DASHBOARD (full AERO-ASTRA)
         ════════════════════════════════════════════ */}
{
  showDashboard && (
    <div className="dashboard-container fade-enter" style={{ paddingTop: '96px', paddingBottom: '36px' }}>
      {activeView === 'about' ? <AboutView /> : (
      <>
      {showScenarioPicker && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(2,3,8,0.75)',
          backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            width: '100%', maxWidth: '640px', background: 'rgba(8,10,18,0.96)',
            border: '1px solid rgba(230,232,236,0.25)', borderRadius: '6px', padding: '28px 32px',
            boxShadow: '0 0 60px rgba(230,232,236,0.08), 0 20px 60px rgba(0,0,0,0.6)',
          }}>
            <div style={{ fontSize: '10px', letterSpacing: '0.3em', color: '#EDEEF2', textTransform: 'uppercase', fontWeight: 'bold', marginBottom: '4px' }}>
              INJECT FAULT SCENARIO
            </div>
            <div className="text-muted" style={{ fontSize: '11px', marginBottom: '20px' }}>
              Runs through the real physics digital twin. Severity decides whether GUARDIAN auto-executes or requires your approval.
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '10px', marginBottom: '22px' }}>
              {Object.values(FAULT_SCENARIOS).map(s => (
                <BorderGlow key={s.key} borderRadius={4} glowRadius={18} fillOpacity={pendingScenario === s.key ? 0.4 : 0.15}
                  backgroundColor={pendingScenario === s.key ? 'rgba(230,232,236,0.1)' : 'rgba(255,255,255,0.02)'}>
                  <div onClick={() => setPendingScenario(s.key)} style={{
                    border: pendingScenario === s.key ? '1px solid #EDEEF2' : '1px solid transparent',
                    borderRadius: '4px', padding: '12px 10px', cursor: 'pointer', transition: 'all 0.15s ease',
                  }}>
                    <div style={{ fontSize: '11px', fontWeight: 'bold', color: pendingScenario === s.key ? '#EDEEF2' : '#ccc', marginBottom: '4px' }}>
                      {s.label}
                    </div>
                    <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', lineHeight: 1.5 }}>{s.summary}</div>
                  </div>
                </BorderGlow>
              ))}
            </div>

            <div style={{ fontSize: '9px', letterSpacing: '0.15em', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', marginBottom: '8px' }}>
              Historical Case Study
            </div>
            <BorderGlow borderRadius={4} glowRadius={22} fillOpacity={pendingScenario === CASE_STUDY_SCENARIO.key ? 0.5 : 0.18}
              backgroundColor={pendingScenario === CASE_STUDY_SCENARIO.key ? 'rgba(255,180,80,0.08)' : 'rgba(255,180,80,0.03)'}>
              <div onClick={() => setPendingScenario(CASE_STUDY_SCENARIO.key)} style={{
                border: pendingScenario === CASE_STUDY_SCENARIO.key ? '1px solid rgba(255,180,80,0.7)' : '1px solid rgba(255,180,80,0.15)',
                borderRadius: '4px', padding: '12px 14px', cursor: 'pointer', transition: 'all 0.15s ease', marginBottom: '22px',
              }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '4px' }}>
                  <span style={{ fontSize: '11px', fontWeight: 'bold', color: pendingScenario === CASE_STUDY_SCENARIO.key ? '#FFC168' : '#ccc' }}>
                    {CASE_STUDY_SCENARIO.label}
                  </span>
                  <span style={{ fontSize: '8px', color: 'rgba(255,180,80,0.7)', letterSpacing: '0.1em' }}>
                    REPLAYS {CASE_STUDY_SCENARIO.citation.incident}
                  </span>
                </div>
                <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.5 }}>{CASE_STUDY_SCENARIO.summary}</div>
              </div>
            </BorderGlow>

            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                <span>Severity</span>
                <span className={pendingSeverity >= HIGH_RISK_SEVERITY_THRESHOLD ? 'text-red' : 'text-green'} style={{ fontWeight: 'bold' }}>
                  {pendingSeverity.toFixed(2)} — {pendingSeverity >= HIGH_RISK_SEVERITY_THRESHOLD ? 'MANUAL_INTERLOCK (human approval)' : 'AUTOMATED_GUARDED (auto-executes)'}
                </span>
              </div>
              <input
                type="range" min="0.3" max="1.0" step="0.05" value={pendingSeverity}
                onChange={e => setPendingSeverity(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: '#EDEEF2' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setShowScenarioPicker(false)} style={{
                flex: 1, padding: '10px', background: 'transparent', border: '1px solid #1f2833', color: '#888',
                cursor: 'pointer', fontFamily: 'inherit', textTransform: 'uppercase', fontSize: '11px', borderRadius: '4px',
              }}>
                Cancel
              </button>
              <button onClick={launchScenario} className="action-btn" style={{ flex: 2, marginTop: 0 }}>
                Launch Scenario
              </button>
            </div>
          </div>
        </div>
      )}

      {scenarioPhase === 'resolved' && activeScenario?.isCaseStudy && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(2,3,8,0.8)',
          backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
        }}>
          <div style={{
            width: '100%', maxWidth: '600px', background: 'rgba(10,8,4,0.97)',
            border: '1px solid rgba(255,180,80,0.4)', borderRadius: '6px', padding: '28px 32px',
            boxShadow: '0 0 60px rgba(255,180,80,0.1), 0 20px 60px rgba(0,0,0,0.6)',
          }}>
            <div style={{ fontSize: '9px', letterSpacing: '0.2em', color: '#FFC168', textTransform: 'uppercase', marginBottom: '6px' }}>
              Preventive Measure — {activeScenario.citation.incident}
            </div>
            <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#EDEEF2', marginBottom: '14px', lineHeight: 1.5 }}>
              If AERO-ASTRA had been running, this failure would not have gone undetected.
            </div>
            <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.75)', lineHeight: 1.7, marginBottom: '14px' }}>
              {activeScenario.citation.note} In this replay, SENTINEL's Engine C (residual correlation) flagged the
              attitude_error / reaction_wheel_speed co-divergence within seconds of onset — well before either
              channel alone crossed an absolute threshold — giving GUARDIAN and ATHENA time to act before the
              condition could become structurally unrecoverable.
            </div>
            <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.4)', lineHeight: 1.6, marginBottom: '20px', fontStyle: 'italic' }}>
              Source: {activeScenario.citation.source}
            </div>
            <button onClick={resetSystem} className="action-btn" style={{ marginTop: 0 }}>
              Return to Monitoring
            </button>
          </div>
        </div>
      )}

      <div className="main-content">
        {/* ── LEFT SIDEBAR ── */}
        <div className="sidebar">
          <div className="panel">
            <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>TELEMETRY STREAM</span>
              {isAnomaly && (
                <button onClick={() => setShowDiff(v => !v)} style={{
                  background: showDiff ? 'rgba(230,232,236,0.15)' : 'transparent',
                  border: '1px solid rgba(230,232,236,0.4)', color: '#EDEEF2',
                  fontSize: '9px', padding: '2px 8px', letterSpacing: '0.05em',
                  textTransform: 'uppercase', cursor: 'pointer', fontFamily: 'inherit', borderRadius: '3px',
                }}>
                  {showDiff ? 'Hide Diff' : 'See Difference'}
                </button>
              )}
            </div>
            <div className="text-muted" style={{ fontSize: '10px', marginBottom: '6px' }}>OPSSAT‑AD Live Telemetry Sync: OK</div>
            {showDiff && isAnomaly ? (
              <div style={{ background: '#000', border: '1px solid #1f2833', fontSize: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', padding: '6px 8px', borderBottom: '1px dashed #1f2833', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '9px' }}>
                  <span>Param</span><span>Baseline</span><span>Live</span>
                </div>
                {TELEMETRY_ROWS.map(row => {
                  const changed = liveTelemetry[row.key] !== BASELINE_TELEMETRY[row.key];
                  return (
                    <div key={row.key} style={{
                      display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', padding: '6px 8px',
                      background: changed ? 'rgba(255,59,59,0.08)' : 'transparent',
                      borderBottom: '1px solid #0f1318',
                    }}>
                      <span style={{ color: 'rgba(255,255,255,0.55)' }}>{row.label}</span>
                      <span style={{ color: 'rgba(255,255,255,0.35)', textDecoration: changed ? 'line-through' : 'none' }}>{BASELINE_TELEMETRY[row.key]}</span>
                      <span className={changed ? 'text-red' : 'text-cyan'} style={{ fontWeight: changed ? 'bold' : 'normal' }}>{liveTelemetry[row.key]}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ background: '#000', padding: '10px', border: '1px solid #1f2833', fontSize: '11px', lineHeight: 1.7 }}>
                {TELEMETRY_ROWS.map(row => {
                  const changed = isAnomaly && liveTelemetry[row.key] !== BASELINE_TELEMETRY[row.key];
                  return (
                    <div key={row.key} className="data-row">
                      <span>{row.label}:</span>
                      <span className={changed ? 'text-red dot-blink' : 'text-cyan'}>{liveTelemetry[row.key]}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="panel">
            <BorderGlow borderRadius={6} glowRadius={16} fillOpacity={0.15}
              backgroundColor={isAnomaly ? 'rgba(255,59,59,0.05)' : 'rgba(255,255,255,0.02)'}>
              <div style={{
                padding: '10px', textAlign: 'center', fontWeight: 'bold', fontSize: '12px',
              }} className={isAnomaly ? 'text-red' : 'text-green'}>
                {isAnomaly ? '⚠ ANOMALY DETECTED' : '✓ SYSTEM NOMINAL'}
              </div>
            </BorderGlow>
            <BorderGlow borderRadius={6} glowRadius={16} fillOpacity={0.25} className="trigger-btn-glow">
              <button onClick={openScenarioPicker} className={`shiny-btn ${isAnomaly ? 'shiny-btn--danger' : ''}`}>
                {isAnomaly ? 'Reset System' : 'Inject Anomaly'}
              </button>
            </BorderGlow>
          </div>

          <div className="panel flex-1">
            <AgentNav
              agents={AGENT_ROSTER}
              activeAgent={activeAgentPage}
              onSelect={code => setActiveAgentPage(code)}
            />
          </div>
        </div>

        {activeAgentPage ? (
          <AgentDetailPage
            agent={activeAgentPage}
            activeScenario={activeScenario}
            activeSeverity={activeSeverity}
            isAnomaly={isAnomaly}
            scenarioPhase={scenarioPhase}
            guardianTier={guardianTier}
            guardianApproved={guardianApproved}
            handleApprove={handleApprove}
            selectedMitigation={selectedMitigation}
            setSelectedMitigation={setSelectedMitigation}
            executeRunbook={executeRunbook}
            logs={logs}
            liveTelemetry={liveTelemetry}
            BASELINE_TELEMETRY={BASELINE_TELEMETRY}
            TELEMETRY_ROWS={TELEMETRY_ROWS}
            backendOnline={backendOnline}
            backendData={backendData}
          />
        ) : (
        <>
        {/* ── CENTER ── */}
        <div className="center-layout">
          <div className="center-view">
            {isAnomaly && <div className="emergency-overlay" />}
            <div className="overlay-status">
              <span className={`status-indicator${isAnomaly ? ' red' : ''}`} />
              ORACLE: DIGITAL TWIN LIVE
            </div>
            <ModelViewer
              url="/simple_satellite_low_poly_free.glb"
              width="100%"
              height="100%"
              autoRotate={!isAnomaly}
              autoRotateSpeed={0.5}
              enableManualRotation={!isAnomaly}
              enableMouseParallax={!isAnomaly}
              enableHoverRotation={!isAnomaly}
              environmentPreset="warehouse"
              defaultZoom={0.8}
              defaultRotationX={20}
              defaultRotationY={-50}
              modelXOffset={isAnomaly ? -0.16 : 0}
              lockRotation={isAnomaly}
              lockRotationX={8}
              lockRotationY={90}
              showScreenshotButton={false}
            />
          </div>

          <div className="bottom-bar">
            <div className="bottom-section">
              <div className="panel-title">AGENT: QUARTERMASTER (SANDBOX)</div>
              {(scenarioPhase === 'planning' || scenarioPhase === 'awaiting_approval' || scenarioPhase === 'executing') ? (
                <div style={{ fontSize: '12px', marginTop: '8px', lineHeight: 1.7 }}>
                  Simulating mitigation options...<br />
                  <span className="text-cyan">Selected: Option {selectedMitigation}</span><br />
                  <span className={selectedMitigation === 1 ? 'text-green' : 'text-red'}>
                    {selectedMitigation === 1 ? 'Confidence: 98% (Safe)' : 'Risk: 15% System Loss (CRITICAL)'}
                  </span>
                </div>
              ) : (
                <div className="text-muted" style={{ fontSize: '11px', marginTop: '10px' }}>Standby for mitigation models.</div>
              )}
            </div>

            <div className="bottom-section">
              <div className="panel-title">AGENT: GUARDIAN (SAFETY GATE)</div>
              {guardianTier === 'AUTOMATED_GUARDED' ? (
                <div style={{ fontSize: '11px', marginTop: '10px', lineHeight: 1.6 }}>
                  <span className="text-green" style={{ fontWeight: 'bold' }}>● AUTOMATED_GUARDED</span>
                  <div className="text-muted" style={{ marginTop: '4px' }}>Low severity — executing without human approval.</div>
                </div>
              ) : (
                <>
                  <div className="slider-container">
                    <label className="switch">
                      <input type="checkbox" disabled={scenarioPhase !== 'awaiting_approval'} checked={guardianApproved} onChange={handleApprove} />
                      <span className="slider" />
                    </label>
                    <span style={{ fontSize: '12px', color: isAnomaly ? '#fff' : '#666' }}>Approve Primary Mitigation</span>
                  </div>
                  {isAnomaly && <div className="text-red" style={{ fontSize: '10px', marginTop: '6px' }}>MANUAL_INTERLOCK — human approval required.</div>}
                  {guardianApproved && <div style={{ fontSize: '11px', marginTop: '8px' }} className="text-green">Safety Approval Granted.</div>}
                </>
              )}
            </div>

            <div className="bottom-section" style={{ borderRight: 'none', paddingRight: 0 }}>
              <div className="panel-title">AGENT: SCRIBE (ORCHESTRATOR)</div>
              <div className="text-muted" style={{ fontSize: '11px', marginBottom: '8px' }}>Execute action and generate audit runbook.</div>
              <button className="action-btn" disabled={!guardianApproved || scenarioPhase !== 'awaiting_approval' || guardianTier === 'AUTOMATED_GUARDED'} onClick={() => executeRunbook()}>
                {scenarioPhase === 'executing' ? 'EXECUTING...' : guardianTier === 'AUTOMATED_GUARDED' ? 'AUTO-EXECUTING...' : 'EXECUTE RUNBOOK'}
              </button>
            </div>
          </div>
        </div>

        {/* ── RIGHT SIDEBAR ── */}
        <div className="sidebar right-panel">
          <div className="panel">
            <div className="panel-title">MISSION TIMELINE</div>
            <div className="mission-timeline">
              {MISSION_STAGES.map(stage => {
                const phaseIdx = PHASE_ORDER.indexOf(scenarioPhase);
                const state = scenarioPhase === 'nominal' ? 'idle'
                  : scenarioPhase === 'resolved' ? 'done'
                  : phaseIdx > stage.minPhaseIdx ? 'done'
                  : phaseIdx === stage.minPhaseIdx ? 'active'
                  : 'pending';
                return (
                  <div key={stage.code} className={`timeline-stage timeline-stage--${state}`}>
                    <span className="timeline-dot" />
                    <span className="timeline-label">{stage.code}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel flex-1">
            <div className="panel-title">GROUND CONTACT</div>
            <div className="data-row"><span>Next AOS</span><span className="text-cyan">{missionStart ? `T-${Math.max(0, 8 - Math.floor(((Date.now() - missionStart) / 1000) % 480 / 60))} min` : 'T-8 min'}</span></div>
            <div className="data-row"><span>Station</span><span>SVALBARD (SG3)</span></div>
            <div className="data-row"><span>Orbit</span><span className="text-cyan">#{missionStart ? 4127 + Math.floor((Date.now() - missionStart) / 5400000) : 4127}</span></div>
            <div className="data-row"><span>Alt / Vel</span><span>540 km | 7.5 km/s</span></div>
            <div className="text-muted" style={{ fontSize: '9px', marginTop: '8px', lineHeight: 1.5 }}>
              Simulated pass schedule — QUARTERMASTER will replace this with real fleet coordination once built.
            </div>
          </div>

          <div className="panel" style={{ gap: '10px', display: 'flex', flexDirection: 'column' }}>
            <div className="panel-title" style={{ marginBottom: 0 }}>SYSTEM RESOURCES</div>
            <SystemMeter label="CPU" />
            <SystemMeter label="GPU" />
            <SystemMeter label="NET" />
            <SystemMeter label="SENS" />
          </div>
        </div>
        </>
        )}
      </div>
      </>
      )}

      {/* Footer */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0, height: '36px',
        background: 'rgba(0,0,0,0.6)', borderTop: '1px solid #1f2833',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px',
        fontSize: '9px', fontFamily: 'monospace', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.4)',
        textTransform: 'uppercase', zIndex: 40,
      }}>
        <span>ISRO NETRA FEED: <span style={{ color: '#00FF88' }}>● LIVE</span></span>
        <div style={{ display: 'flex', gap: '20px' }}><SystemMeter label="CPU" /><SystemMeter label="NET" /></div>
        <span>AERO‑ASTRA MISSION OPS v2.5 <span style={{ color: '#EDEEF2' }}>✓ NOMINAL</span></span>
      </div>
    </div>
  )
}
    </div >
  );
}

export default App;
