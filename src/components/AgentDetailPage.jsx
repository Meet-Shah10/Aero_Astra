import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';
import BorderGlow from './BorderGlow';
import OracleView from './oracle/OracleView.jsx';
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

// Mirrors backend/sherlock/graph.py's SatelliteGraph exactly — 6 nodes, 18
// directed edges. An edge A -> B means "a fault in A can propagate to or
// cause a fault in B," so SHERLOCK's candidate set for a flagged subsystem
// is {itself} union {direct predecessors} — every node with an edge pointing
// INTO it. This is what makes the LLM's diagnosis unable to hallucinate: it
// can only ever pick from this graph-computed set.
const DEPENDENCY_SUBSYSTEMS = ['EPS', 'TCS', 'ADCS', 'OBC', 'TT&C', 'Propulsion'];
const DEPENDENCY_EDGES = [
  ['EPS', 'TCS'], ['EPS', 'ADCS'], ['EPS', 'OBC'], ['EPS', 'TT&C'], ['EPS', 'Propulsion'],
  ['TCS', 'ADCS'], ['TCS', 'OBC'], ['TCS', 'EPS'], ['TCS', 'Propulsion'],
  ['ADCS', 'TCS'], ['ADCS', 'EPS'], ['ADCS', 'TT&C'],
  ['OBC', 'ADCS'], ['OBC', 'TT&C'], ['OBC', 'EPS'],
  ['TT&C', 'OBC'],
  ['Propulsion', 'ADCS'], ['Propulsion', 'TCS'],
];

// Hexagon layout, EPS at 12 o'clock, clockwise.
const HEX_R = 108;
const HEX_CENTER = 140;
const DEPENDENCY_POSITIONS = Object.fromEntries(
  DEPENDENCY_SUBSYSTEMS.map((s, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / DEPENDENCY_SUBSYSTEMS.length;
    return [s, { x: HEX_CENTER + HEX_R * Math.cos(angle), y: HEX_CENTER + HEX_R * Math.sin(angle) }];
  })
);

// Full 6-node/18-edge dependency graph, with the flagged subsystem's
// candidate set (graph-computed predecessors) and the confirmed causal
// chain highlighted on top of it — this is what actually constrains
// SHERLOCK's LLM call on the backend, not just the one chain that fired.
function DependencyGraph({ flaggedSubsystem, causalChain }) {
  const candidateSet = new Set([
    flaggedSubsystem,
    ...DEPENDENCY_EDGES.filter(([, to]) => to === flaggedSubsystem).map(([from]) => from),
  ]);
  const chainSet = new Set(causalChain);
  const chainEdgeSet = new Set(
    causalChain.slice(0, -1).map((s, i) => `${s}->${causalChain[i + 1]}`)
  );

  return (
    <div className="dep-graph-wrap">
      <svg width={280} height={280} viewBox="0 0 280 280">
        <defs>
          <marker id="dep-arrow-dim" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="rgba(255,255,255,0.15)" />
          </marker>
          <marker id="dep-arrow-candidate" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="rgba(255,190,90,0.7)" />
          </marker>
          <marker id="dep-arrow-chain" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
            <path d="M0,0 L7,3.5 L0,7 Z" fill="#52ff52" />
          </marker>
        </defs>

        {DEPENDENCY_EDGES.map(([from, to]) => {
          const a = DEPENDENCY_POSITIONS[from];
          const b = DEPENDENCY_POSITIONS[to];
          const isChainEdge = chainEdgeSet.has(`${from}->${to}`);
          const isCandidateEdge = to === flaggedSubsystem;
          const dx = b.x - a.x, dy = b.y - a.y;
          const len = Math.hypot(dx, dy);
          const ux = dx / len, uy = dy / len;
          const NR = 22;
          const x1 = a.x + ux * NR, y1 = a.y + uy * NR;
          const x2 = b.x - ux * NR, y2 = b.y - uy * NR;
          return (
            <line
              key={`${from}-${to}`}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={isChainEdge ? '#52ff52' : isCandidateEdge ? 'rgba(255,190,90,0.7)' : 'rgba(255,255,255,0.15)'}
              strokeWidth={isChainEdge ? 2.2 : isCandidateEdge ? 1.6 : 1}
              markerEnd={`url(#dep-arrow-${isChainEdge ? 'chain' : isCandidateEdge ? 'candidate' : 'dim'})`}
            />
          );
        })}

        {DEPENDENCY_SUBSYSTEMS.map(s => {
          const p = DEPENDENCY_POSITIONS[s];
          const isFlagged = s === flaggedSubsystem;
          const isChain = chainSet.has(s);
          const isCandidate = candidateSet.has(s) && !isChain;
          const fill = isChain ? 'rgba(82,255,82,0.14)' : isFlagged ? 'rgba(255,90,90,0.14)' : isCandidate ? 'rgba(255,190,90,0.1)' : 'rgba(255,255,255,0.03)';
          const stroke = isChain ? '#52ff52' : isFlagged ? '#ff5a5a' : isCandidate ? 'rgba(255,190,90,0.8)' : 'rgba(255,255,255,0.25)';
          return (
            <g key={s}>
              <circle cx={p.x} cy={p.y} r={22} fill={fill} stroke={stroke} strokeWidth={isChain || isFlagged ? 2 : 1.2} />
              <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize="9.5" fontWeight="700"
                fontFamily="var(--font-mono)" fill={isChain ? '#52ff52' : isFlagged ? '#ff5a5a' : '#EDEEF2'}>
                {s}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="dep-graph-legend">
        <div><i className="dep-legend-swatch" style={{ background: 'rgba(255,90,90,0.8)' }} /> Flagged subsystem (SENTINEL)</div>
        <div><i className="dep-legend-swatch" style={{ background: 'rgba(255,190,90,0.8)' }} /> Graph-valid candidates (physically possible)</div>
        <div><i className="dep-legend-swatch" style={{ background: '#52ff52' }} /> Confirmed causal chain</div>
      </div>
    </div>
  );
}

function SentinelPage({ activeScenario, activeSeverity, isAnomaly, hasIncidentData, TELEMETRY_ROWS, BASELINE_TELEMETRY, liveTelemetry, backendOnline, backendData }) {
  const liveTm = backendOnline ? backendData?.telemetry : null;
  // Metadata rows are real, derived state — not decoration. baseline is
  // always the clean-run snapshot; live reflects whatever's actually active.
  // Gated on hasIncidentData (not isAnomaly) so the last run's values stay
  // visible after it resolves instead of snapping back to baseline —
  // AUTOMATED_GUARDED scenarios auto-resolve in ~5s, too fast to read.
  const metaRows = [
    { key: '__fault', label: 'active_fault', baseline: 'none', live: hasIncidentData ? activeScenario.faultId : 'none' },
    { key: '__severity', label: 'severity', baseline: '0.00', live: hasIncidentData ? activeSeverity.toFixed(2) : '0.00' },
    { key: '__subsystem', label: 'flagged_subsystem', baseline: '—', live: hasIncidentData ? activeScenario.subsystem : '—' },
  ];
  const dataRows = TELEMETRY_ROWS.map(row => ({
    key: row.key,
    label: row.label,
    baseline: BASELINE_TELEMETRY[row.key],
    live: hasIncidentData ? liveTelemetry[row.key] : BASELINE_TELEMETRY[row.key],
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
              const changed = hasIncidentData && row.live !== row.baseline;
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
              const changed = hasIncidentData && row.live !== row.baseline;
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

function SherlockPage({ activeScenario, isAnomaly, hasIncidentData, liveTelemetry }) {
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

  if (!hasIncidentData || !activeScenario) {
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

      <div className="dep-graph-section">
        <div className="dep-graph-section-title">FULL DEPENDENCY GRAPH — why these candidates, not others</div>
        <p className="text-muted" style={{ fontSize: 10, marginBottom: 12, lineHeight: 1.6 }}>
          6 subsystems, 18 directed edges (backend/sherlock/graph.py). Given the subsystem SENTINEL flagged, the
          only physically valid root causes are itself plus every subsystem with an edge pointing into it — the LLM's
          diagnosis is constrained to this set before it ever runs, so it cannot claim a root cause the graph rules out.
        </p>
        <DependencyGraph flaggedSubsystem={activeScenario.subsystem} causalChain={chain} />
      </div>

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

// OraclePage: thin shell — OracleView owns its own state machine and layout.
// We pass through backendOnline, backendData, and hasIncidentData (not
// isAnomaly — see the App.jsx note on hasIncidentData) so OracleView both
// auto-triggers when the backend oracle_simulation WS message arrives and
// keeps showing the last run's real numbers after it resolves, instead of
// resetting to DORMANT the instant AUTOMATED_GUARDED auto-resolves (~5s).
function OraclePage({ hasIncidentData, backendOnline, backendData }) {
  return (
    <OracleView
      isAnomaly={hasIncidentData}
      backendOnline={backendOnline}
      backendData={backendData}
    />
  );
}

function AthenaPage({ hasIncidentData, scenarioPhase, selectedMitigation, setSelectedMitigation, backendOnline, backendData }) {
  if (!hasIncidentData) return <Empty label="No mitigation required." />;
  const ready = scenarioPhase === 'planning' || scenarioPhase === 'awaiting_approval' || scenarioPhase === 'executing' || scenarioPhase === 'resolved';
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

function GuardianPage({ hasIncidentData, guardianTier, guardianApproved, scenarioPhase, handleApprove }) {
  return (
    <>
      <p className="agent-page-lede">
        Low-severity events auto-execute and log themselves (AUTOMATED_GUARDED). High-severity events lock
        until a human explicitly approves (MANUAL_INTERLOCK) — nothing executes without it.
      </p>
      {!hasIncidentData ? (
        <Empty label="Safety gate armed and nominal. No pending decision." />
      ) : !guardianTier ? (
        <Empty label="Awaiting SHERLOCK diagnosis before GUARDIAN can classify severity..." />
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

function ScribePage({ isAnomaly, scenarioPhase, guardianTier, guardianApproved, executeRunbook, scribeReport }) {
  const canExecute = isAnomaly && (guardianTier === 'AUTOMATED_GUARDED' || guardianApproved) && scenarioPhase === 'awaiting_approval';
  return (
    <>
      <p className="agent-page-lede">Compiles every agent's decision, timestamps, and reasoning into an operator-ready audit runbook.</p>
      {!isAnomaly && !scribeReport ? (
        <Empty label="No incident to record." />
      ) : (
        <>
          {!scribeReport && (
            <button className="action-btn" disabled={!canExecute} onClick={executeRunbook} style={{ maxWidth: 280, marginBottom: 20 }}>
              {scenarioPhase === 'executing' ? 'EXECUTING...' : 'EXECUTE RUNBOOK'}
            </button>
          )}
          {scenarioPhase === 'executing' && !scribeReport && (
            <div className="text-muted" style={{ fontSize: 11 }}>Compiling audit runbook from SENTINEL/SHERLOCK/ORACLE/ATHENA/GUARDIAN records...</div>
          )}
          {scribeReport && (
            <div className="scribe-report">
              <div className="scribe-report-head">
                <span className="live-data-badge">● AUDIT RUNBOOK — generated {new Date(scribeReport.generatedAt).toLocaleTimeString()}</span>
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">01 · INCIDENT</div>
                <div className="scribe-kv"><span>Scenario</span><span>{scribeReport.scenario}</span></div>
                <div className="scribe-kv"><span>Fault ID</span><span>{scribeReport.faultId}</span></div>
                <div className="scribe-kv"><span>Subsystem</span><span>{scribeReport.subsystem}</span></div>
                <div className="scribe-kv"><span>Severity</span><span>{scribeReport.severity?.toFixed(2)}</span></div>
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">02 · DETECTION (SENTINEL)</div>
                {scribeReport.sentinel ? (
                  <>
                    <div className="scribe-kv"><span>Engine</span><span>{scribeReport.sentinel.triggered_engine}</span></div>
                    <div className="scribe-kv"><span>Timestamp</span><span>t={scribeReport.sentinel.timestamp}s</span></div>
                  </>
                ) : <div className="text-muted" style={{ fontSize: 10 }}>No SENTINEL record for this run.</div>}
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">03 · DIAGNOSIS (SHERLOCK)</div>
                {scribeReport.sherlock ? (
                  <>
                    <div className="scribe-kv"><span>Root cause</span><span>{scribeReport.sherlock.primary_root_cause}</span></div>
                    <div className="scribe-kv"><span>Urgency</span><span>{scribeReport.sherlock.urgency}</span></div>
                    <div className="scribe-kv"><span>Confidence</span><span>{(scribeReport.sherlock.confidence_score * 100).toFixed(0)}%</span></div>
                  </>
                ) : <div className="text-muted" style={{ fontSize: 10 }}>No SHERLOCK record for this run.</div>}
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">04 · SIMULATION (ORACLE)</div>
                {scribeReport.oracle ? (
                  <>
                    <div className="scribe-kv"><span>Best action</span><span>{scribeReport.oracle.best_action?.replaceAll('_', ' ')}</span></div>
                    <div className="scribe-kv"><span>Safety score</span><span>{scribeReport.oracle.top_score?.toFixed(2)}</span></div>
                  </>
                ) : <div className="text-muted" style={{ fontSize: 10 }}>No ORACLE record for this run.</div>}
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">05 · RECOVERY PLAN (ATHENA)</div>
                {scribeReport.athena ? (
                  <>
                    <div className="scribe-kv"><span>Recommended</span><span>{scribeReport.athena.recommended_action?.replaceAll('_', ' ')}</span></div>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.55)', marginTop: 4, lineHeight: 1.5 }}>{scribeReport.athena.rationale}</div>
                  </>
                ) : <div className="text-muted" style={{ fontSize: 10 }}>No ATHENA record for this run.</div>}
              </div>

              <div className="scribe-section">
                <div className="scribe-section-title">06 · EXECUTION (GUARDIAN)</div>
                <div className="scribe-kv"><span>Tier</span><span>{scribeReport.guardianTier}</span></div>
                <div className="scribe-kv"><span>Mitigation option</span><span>#{scribeReport.mitigationOption}</span></div>
                <div className="scribe-kv"><span>Result</span><span className="text-green">Nominal</span></div>
              </div>
            </div>
          )}
        </>
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

  // ORACLE owns its full layout — no standard header/body wrapping
  if (agent === 'ORACLE') {
    return (
      <div className="agent-page agent-page--oracle fade-enter">
        <OraclePage {...props} />
      </div>
    );
  }

  return (
    <div className="agent-page fade-enter">
      <div className="agent-page-header">
        <div className="agent-page-code">{agent}</div>
        <div className="agent-page-role">{meta?.role}</div>
      </div>
      <div className={`agent-page-body ${agent === 'SENTINEL' || agent === 'SHERLOCK' ? '' : 'agent-page-body--narrow'}`}>
        {agent === 'SENTINEL' && <SentinelPage {...props} />}
        {agent === 'SHERLOCK' && <SherlockPage {...props} />}

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
