import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';
import BorderGlow from './BorderGlow';
import ResidualChart from './ResidualChart';
import './AgentDetailPage.css';

// Which BASELINE_TELEMETRY/liveTelemetry row each subsystem's fault shows up
// in. ADCS and Propulsion don't have a dedicated row in TELEMETRY_ROWS, so
// their steps fall back to a qualitative read rather than a fabricated number.
const SUBSYSTEM_TELEMETRY_KEY = {
  TCS: 'tcsTemp',
  EPS: 'epsLoad',
  OBC: 'cpuUsage',
  'TT&C': 'commLink',
};

function Empty({ label }) {
  return <div className="agent-page-empty">{label}</div>;
}

function SentinelPage({ activeScenario, activeSeverity, isAnomaly, TELEMETRY_ROWS, BASELINE_TELEMETRY, liveTelemetry, backendOnline, backendData }) {
  const liveTm = backendOnline ? backendData?.telemetry : null;
  // Metadata rows are real, derived state — not decoration. baseline is
  // always the clean-run snapshot; live reflects whatever's actually active.
  const metaRows = [
    { key: '__fault', label: 'active_fault', baseline: 'none', live: isAnomaly ? activeScenario.faultId : 'none' },
    { key: '__severity', label: 'severity', baseline: '0.00', live: isAnomaly ? activeSeverity.toFixed(2) : '0.00' },
    { key: '__subsystem', label: 'flagged_subsystem', baseline: '—', live: isAnomaly ? activeScenario.subsystem : '—' },
  ];
  const dataRows = TELEMETRY_ROWS.map(row => ({
    key: row.key,
    label: row.label,
    baseline: BASELINE_TELEMETRY[row.key],
    live: isAnomaly ? liveTelemetry[row.key] : BASELINE_TELEMETRY[row.key],
  }));
  const rows = [...metaRows, ...dataRows];

  return (
    <>
      <p className="agent-page-lede">
        {isAnomaly
          ? <>Correlation threshold exceeded on <strong>{activeScenario.subsystem}</strong>. Physics digital-twin baseline vs. current live snapshot — changed fields highlighted.</>
          : 'All telemetry within baseline range. Snapshots below are identical — no anomaly currently flagged.'}
      </p>
      {liveTm && (
        <div className="live-data-badge" style={{ marginBottom: 12 }}>
          ● LIVE — backend/api.py 'telemetry' @ t={liveTm.timestamp}s — ADCS.attitude_error={liveTm.subsystems.ADCS.attitude_error.toFixed(3)}°,
          ADCS.wheel={liveTm.subsystems.ADCS.reaction_wheel_speed.toFixed(1)}rpm, EPS.soc={(liveTm.subsystems.EPS.battery_soc * 100).toFixed(1)}%,
          EPS.bus_voltage={liveTm.subsystems.EPS.bus_voltage.toFixed(2)}V
        </div>
      )}
      {backendOnline && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, letterSpacing: '0.1em', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase', marginBottom: 6 }}>
            Engine C — Residual Correlation
          </div>
          <ResidualChart
            residualHistory={backendData?.residualHistory}
            detectTimestamp={backendData?.sentinel?.timestamp}
          />
        </div>
      )}
      <div className="dataset-compare">
        <div className="dataset-pane">
          <div className="dataset-pane-head">PHYSICS_SIMULATOR — BASELINE.SNAPSHOT</div>
          <div className="dataset-pane-body">
            {rows.map((row, i) => {
              const changed = isAnomaly && row.live !== row.baseline;
              return (
                <div key={row.key} className={`dataset-line ${changed ? 'dataset-line--changed' : ''}`}>
                  <span className="dataset-line-no">{String(i + 1).padStart(2, '0')}</span>
                  <span className="dataset-line-key">{row.label}:</span>
                  <span className="dataset-line-val">{row.baseline}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="dataset-pane">
          <div className="dataset-pane-head">LIVE_TELEMETRY — CURRENT.SNAPSHOT</div>
          <div className="dataset-pane-body">
            {rows.map((row, i) => {
              const changed = isAnomaly && row.live !== row.baseline;
              return (
                <div key={row.key} className={`dataset-line ${changed ? 'dataset-line--changed' : ''}`}>
                  <span className="dataset-line-no">{String(i + 1).padStart(2, '0')}</span>
                  <span className="dataset-line-key">{row.label}:</span>
                  <span className={`dataset-line-val ${changed ? 'dataset-line-val--changed' : ''}`}>{row.live}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}

// Node vertical spacing / radius for the SVG causal graph below.
const NODE_GAP = 128;
const NODE_R = 34;
const GRAPH_W = 340;

function SherlockPage({ activeScenario, isAnomaly, liveTelemetry }) {
  const [selected, setSelected] = useState(0);
  const [replayKey, setReplayKey] = useState(0);
  const nodeRefs = useRef([]);
  const edgeRefs = useRef([]);
  const tlRef = useRef(null);

  // chain[0] is always the true root (per FAULT_SCENARIOS) — rendered at the
  // top. chain[last] is the most downstream, visible symptom — at the
  // bottom, since that's what an operator actually sees first.
  const chain = activeScenario ? activeScenario.causalChain : [];
  const n = chain.length;

  useLayoutEffect(() => {
    if (!isAnomaly || n === 0) return;
    setSelected(n - 1);
    nodeRefs.current = nodeRefs.current.slice(0, n);
    edgeRefs.current = edgeRefs.current.slice(0, n - 1);

    const nodes = nodeRefs.current;
    const edges = edgeRefs.current;
    gsap.set(nodes, { scale: 0, opacity: 0, transformOrigin: '50% 50%' });
    gsap.set(edges, { strokeDashoffset: NODE_GAP });

    const tl = gsap.timeline();
    tlRef.current = tl;

    // Reveal from the bottom (symptom, index n-1) upward to the root (index 0).
    for (let i = n - 1; i >= 0; i--) {
      tl.to(nodes[i], { scale: 1, opacity: 1, duration: 0.35, ease: 'back.out(2)' });
      if (i > 0) {
        tl.to(edges[i - 1], { strokeDashoffset: 0, duration: 0.4, ease: 'power2.inOut' }, '-=0.05');
      }
      tl.call(() => setSelected(i));
    }
    tl.to(nodes[0], { duration: 0.15 }); // settle
    tl.call(() => setSelected(0));

    return () => tl.kill();
  }, [activeScenario, isAnomaly, n, replayKey]);

  if (!isAnomaly || !activeScenario) {
    return <Empty label="Awaiting fault trigger — nothing to diagnose yet." />;
  }

  const svgH = (n - 1) * NODE_GAP + NODE_R * 2 + 40;
  const xCenter = GRAPH_W / 2;
  const yFor = i => 20 + NODE_R + i * NODE_GAP;

  const selectedSubsystem = chain[selected];
  const selectedKey = SUBSYSTEM_TELEMETRY_KEY[selectedSubsystem];
  const selectedReading = selectedKey ? liveTelemetry[selectedKey] : 'Elevated deviation detected';
  const isRootSelected = selected === 0;

  return (
    <>
      <p className="agent-page-lede">
        Backtracing from the observed symptom through the causal dependency graph to the true root cause.
      </p>

      <div className="sherlock-layout">
        <div className="causal-graph-wrap">
          <svg width={GRAPH_W} height={svgH} viewBox={`0 0 ${GRAPH_W} ${svgH}`}>
            {chain.slice(0, -1).map((s, i) => (
              <line
                key={`edge-${s}`}
                ref={el => { edgeRefs.current[i] = el; }}
                x1={xCenter} y1={yFor(i) + NODE_R}
                x2={xCenter} y2={yFor(i + 1) - NODE_R}
                stroke="rgba(237,238,242,0.5)"
                strokeWidth="2"
                strokeDasharray={NODE_GAP}
                markerEnd="url(#sherlock-arrow)"
              />
            ))}
            <defs>
              <marker id="sherlock-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 Z" fill="rgba(237,238,242,0.5)" />
              </marker>
            </defs>
            {chain.map((s, i) => {
              const isRoot = i === 0;
              const isSel = i === selected;
              return (
                <g
                  key={s}
                  ref={el => { nodeRefs.current[i] = el; }}
                  onClick={() => setSelected(i)}
                  style={{ cursor: 'pointer' }}
                >
                  <circle
                    cx={xCenter} cy={yFor(i)} r={NODE_R}
                    fill={isRoot ? 'rgba(82,255,82,0.12)' : isSel ? 'rgba(237,238,242,0.12)' : 'rgba(255,255,255,0.03)'}
                    stroke={isRoot ? '#52ff52' : isSel ? '#EDEEF2' : 'rgba(255,255,255,0.25)'}
                    strokeWidth={isSel ? 2 : 1.2}
                  />
                  <text x={xCenter} y={yFor(i) + 4} textAnchor="middle" fontSize="11" fontWeight="700"
                    fontFamily="var(--font-mono)" fill={isRoot ? '#52ff52' : '#EDEEF2'}>
                    {s}
                  </text>
                  {isRoot && (
                    <text x={xCenter} y={yFor(i) - NODE_R - 10} textAnchor="middle" fontSize="9"
                      fontFamily="var(--font-mono)" fill="#52ff52" letterSpacing="1">
                      ROOT CAUSE
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>

        <div className="causal-detail">
          <BorderGlow borderRadius={8} glowRadius={24} fillOpacity={isRootSelected ? 0.5 : 0.18}
            backgroundColor={isRootSelected ? 'rgba(82,255,82,0.05)' : 'rgba(255,255,255,0.02)'}>
            <div className={`causal-box ${isRootSelected ? 'causal-box--root' : ''}`}>
              {isRootSelected && <div className="causal-box-tag">ROOT CAUSE CONFIRMED</div>}
              <div className="causal-box-subsystem">{selectedSubsystem}</div>
              <div className="causal-box-reading">{selectedReading}</div>
              {isRootSelected && <div className="causal-box-verdict">{activeScenario.rootCause}</div>}
            </div>
          </BorderGlow>
          <button className="causal-nav-btn" style={{ marginTop: 14 }} onClick={() => setReplayKey(k => k + 1)}>
            ↻ Replay trace
          </button>
        </div>
      </div>
    </>
  );
}

function OraclePage({ isAnomaly, backendOnline, backendData }) {
  if (!isAnomaly) return <Empty label="Standby — no simulation requested." />;
  const oracle = backendOnline ? backendData?.oracle : null;
  if (!oracle) return <Empty label="Waiting for SENTINEL/SHERLOCK before simulation can run..." />;
  const results = oracle.results || [];
  return (
    <>
      <p className="agent-page-lede">100 independent Monte Carlo runs per candidate action against the physics digital twin.</p>
      <div className="live-data-badge" style={{ marginBottom: 12 }}>
        ● LIVE — backend/oracle/agent.py — best_action={oracle.best_action}, top_score={oracle.top_score?.toFixed(2)}, mode={oracle.mode}
      </div>
      <div className="oracle-bars">
        {results.length === 0 && (
          <div className="text-muted" style={{ fontSize: 11 }}>No candidate actions returned by ORACLE for this fault.</div>
        )}
        {results.map(r => {
          const pct = Math.round(r.nominal_recovery_rate * 100);
          const bad = r.mission_loss_rate > 0.15;
          return (
            <div className="oracle-bar-row" key={r.action_name}>
              <span>{r.action_name.replaceAll('_', ' ')}</span>
              <div className="oracle-bar">
                <div className={`oracle-bar-fill ${bad ? 'oracle-bar-fill--bad' : ''}`} style={{ width: `${pct}%` }} />
              </div>
              <span className={bad ? 'text-red' : 'text-green'}>
                {pct}% recovery{r.mission_loss_rate > 0 ? ` · ${Math.round(r.mission_loss_rate * 100)}% loss risk` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}

function AthenaPage({ isAnomaly, scenarioPhase, selectedMitigation, setSelectedMitigation, backendOnline, backendData }) {
  if (!isAnomaly) return <Empty label="No mitigation required." />;
  const ready = scenarioPhase === 'planning' || scenarioPhase === 'awaiting_approval' || scenarioPhase === 'executing';
  if (!ready) return <Empty label="Waiting for SHERLOCK diagnosis before options can be generated..." />;
  const athena = backendOnline ? backendData?.athena : null;
  if (!athena) return <Empty label="Waiting for ORACLE simulation before ATHENA can plan..." />;
  const options = athena.options && athena.options.length > 0
    ? athena.options
    : [{ action_name: athena.recommended_action, procedure_steps: [], safety_score: null, effectiveness_score: null, predicted_outcome: athena.rationale }];
  return (
    <>
      <p className="agent-page-lede">Recovery options ranked by ORACLE's simulated outcomes. Select to change the primary plan.</p>
      {athena.offline_fallback && (
        <div className="text-muted" style={{ fontSize: 10, marginBottom: 10 }}>
          ATHENA LLM unavailable this run — options below are ORACLE's real Monte Carlo results, ranked deterministically (no LLM commentary).
        </div>
      )}
      <div className="athena-options">
        {options.map((opt, i) => (
          <div key={opt.action_name} onClick={() => scenarioPhase !== 'executing' && setSelectedMitigation(i + 1)}
            className={`athena-option ${selectedMitigation === i + 1 ? 'is-selected' : ''}`}>
            <div className="athena-option-title">{i + 1}. {opt.action_name?.replaceAll('_', ' ')}</div>
            {opt.effectiveness_score != null && (
              <div className={`athena-option-meta ${opt.effectiveness_score >= 0.7 ? 'text-green' : 'text-red'}`}>
                Nominal recovery: {Math.round(opt.effectiveness_score * 100)}%
                {opt.is_irreversible ? ' · IRREVERSIBLE' : ''}
              </div>
            )}
            {opt.predicted_outcome && (
              <div className="text-muted" style={{ fontSize: 10, marginTop: 4 }}>{opt.predicted_outcome}</div>
            )}
            {opt.procedure_steps && opt.procedure_steps.length > 0 && (
              <ol style={{ fontSize: 10, marginTop: 6, paddingLeft: 16, color: 'rgba(255,255,255,0.6)' }}>
                {opt.procedure_steps.map((s, j) => <li key={j}>{s}</li>)}
              </ol>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function GuardianPage({ isAnomaly, guardianTier, guardianApproved, scenarioPhase, handleApprove }) {
  return (
    <>
      <p className="agent-page-lede">
        Low-severity events auto-execute and log themselves (AUTOMATED_GUARDED). High-severity events lock
        until a human explicitly approves (MANUAL_INTERLOCK) — nothing executes without it.
      </p>
      {!isAnomaly ? (
        <Empty label="Safety gate armed and nominal. No pending decision." />
      ) : guardianTier === 'AUTOMATED_GUARDED' ? (
        <div className="guardian-status">
          <span className="guardian-tier-badge guardian-tier-badge--auto">● AUTOMATED_GUARDED</span>
          <p>Severity below the human-approval threshold — executing without waiting for approval.</p>
        </div>
      ) : (
        <div className="guardian-status">
          <span className="guardian-tier-badge guardian-tier-badge--manual">● MANUAL_INTERLOCK</span>
          <div className="slider-container" style={{ marginTop: 14 }}>
            <label className="switch">
              <input type="checkbox" disabled={scenarioPhase !== 'awaiting_approval'} checked={guardianApproved} onChange={handleApprove} />
              <span className="slider" />
            </label>
            <span style={{ fontSize: 12 }}>Approve Primary Mitigation</span>
          </div>
          {guardianApproved && <p className="text-green" style={{ marginTop: 10 }}>Safety approval granted.</p>}
        </div>
      )}
    </>
  );
}

function QuartermasterPage({ isAnomaly, activeScenario }) {
  return (
    <>
      <p className="agent-page-lede">Ground-station coordination and fleet load-shifting. Marked PLANNED — not wired to a live scheduler yet.</p>
      {isAnomaly ? (
        <div className="qm-note">
          <div>If {activeScenario?.subsystem} load must be offloaded, QUARTERMASTER would shift it to the next
            available satellite in the fleet and log the handoff window.</div>
        </div>
      ) : (
        <Empty label="Standby for mitigation models." />
      )}
    </>
  );
}

function ScribePage({ isAnomaly, scenarioPhase, guardianTier, guardianApproved, executeRunbook }) {
  const canExecute = isAnomaly && (guardianTier === 'AUTOMATED_GUARDED' || guardianApproved) && scenarioPhase === 'awaiting_approval';
  return (
    <>
      <p className="agent-page-lede">Compiles every agent's decision, timestamps, and reasoning into an operator-ready audit runbook.</p>
      {!isAnomaly ? (
        <Empty label="No incident to record." />
      ) : (
        <button className="action-btn" disabled={!canExecute} onClick={executeRunbook} style={{ maxWidth: 280 }}>
          {scenarioPhase === 'executing' ? 'EXECUTING...' : 'EXECUTE RUNBOOK'}
        </button>
      )}
    </>
  );
}

function ChroniclePage({ logs }) {
  return (
    <div className="chronicle-full-log">
      {logs.map((log, i) => (
        <p key={i} className={log.includes('WARN') || log.includes('⚠') ? 'text-red' : ''}>{log}</p>
      ))}
    </div>
  );
}

function VitalsPage({ isAnomaly, backendOnline, backendData }) {
  const live = backendOnline ? backendData?.vitals : null;
  return (
    <div className="vitals-grid">
      {live ? (
        <>
          <div className="live-data-badge">● LIVE — from backend/vitals/agent.py::calculate_vitals()</div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">EPS Health</span>
            <span className={live.eps_health < 0.85 ? 'text-red' : 'text-green'}>{(live.eps_health * 100).toFixed(1)}%</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">TCS Health</span>
            <span className={live.tcs_health < 0.85 ? 'text-red' : 'text-green'}>{(live.tcs_health * 100).toFixed(1)}%</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">ADCS Health</span>
            <span className={live.adcs_health < 0.85 ? 'text-red' : 'text-green'}>{(live.adcs_health * 100).toFixed(1)}%</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">Worst Subsystem</span>
            <span className={live.worst_health < 0.85 ? 'text-red' : 'text-green'}>{(live.worst_health * 100).toFixed(1)}%</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">System Health (mean)</span>
            <span>{(live.system_health * 100).toFixed(1)}%</span>
          </div>
        </>
      ) : (
        <>
          <div className="text-muted" style={{ fontSize: 10, marginBottom: 8 }}>
            {backendOnline ? 'Waiting for first vitals_update...' : 'Backend offline — showing simulated display values.'}
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">Subsystem Health</span>
            <span className={isAnomaly ? 'text-red' : 'text-green'}>{isAnomaly ? 'CRITICAL' : 'OPTIMAL'}</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">EPS_SOC</span>
            <span>{isAnomaly ? '85.2% (DEGRADING)' : '98.5%'}</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">TCS_TEMP</span>
            <span>{isAnomaly ? '+4.2°C/hr' : 'Stable'}</span>
          </div>
          <div className="vitals-stat">
            <span className="vitals-stat-label">Attitude</span>
            <span>{isAnomaly ? 'DRIFT 0.3°' : 'Nominal'}</span>
          </div>
          {isAnomaly && <div className="vitals-warning">⚠ WARNING: RUL ESTIMATE 12 ORBITS</div>}
        </>
      )}
    </div>
  );
}

const AGENT_META = {
  SENTINEL: { role: 'The Early Warning System' },
  SHERLOCK: { role: 'The Detective' },
  ORACLE: { role: 'The Simulator' },
  ATHENA: { role: 'The Strategist' },
  GUARDIAN: { role: 'The Safety Gate' },
  QUARTERMASTER: { role: 'The Logistics Manager' },
  SCRIBE: { role: 'The Accountant' },
  CHRONICLE: { role: 'The Live Log' },
  VITALS: { role: 'The Proactive Monitor' },
};

export default function AgentDetailPage({ agent, ...props }) {
  const meta = AGENT_META[agent];
  return (
    <div className="agent-page fade-enter">
      <div className="agent-page-header">
        <div className="agent-page-code">{agent}</div>
        <div className="agent-page-role">{meta?.role}</div>
      </div>
      <div className={`agent-page-body ${agent === 'SENTINEL' || agent === 'SHERLOCK' ? '' : 'agent-page-body--narrow'}`}>
        {agent === 'SENTINEL' && <SentinelPage {...props} />}
        {agent === 'SHERLOCK' && <SherlockPage {...props} />}
        {agent === 'ORACLE' && <OraclePage {...props} />}
        {agent === 'ATHENA' && <AthenaPage {...props} />}
        {agent === 'GUARDIAN' && <GuardianPage {...props} />}
        {agent === 'QUARTERMASTER' && <QuartermasterPage {...props} />}
        {agent === 'SCRIBE' && <ScribePage {...props} />}
        {agent === 'CHRONICLE' && <ChroniclePage {...props} />}
        {agent === 'VITALS' && <VitalsPage {...props} />}
      </div>
    </div>
  );
}
