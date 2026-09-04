/**
 * OracleView — Root component for the ORACLE Monte Carlo simulation panel.
 *
 * THREE DISTINCT RENDER PATHS:
 *   DORMANT    — no anomaly / no request yet. Single centered message.
 *   PROCESSING — simulation animating. Progress panel + live ranked table.
 *   RESULT     — all actions scored. Full rich layout.
 *
 * DATA SOURCES (priority order):
 *   1. Real backend WebSocket data (`backendData.oracle`) when `backendOnline`
 *      and `isAnomaly` are both true. The adapter (oracleAdapter.js) maps the
 *      flat backend message → rich UI state, then plays a PROCESSING animation
 *      seeded with real action names before resolving to real RESULT numbers.
 *   2. Mock simulator (oracleFixture.js) as a fallback when backend is offline
 *      — identical state shape, so no component changes needed.
 *
 * Props:
 *   backendOnline  {boolean}  — is the WS connected?
 *   backendData    {object}   — latest messages keyed by agent; oracle key holds
 *                              the `oracle_simulation` WS message.
 *   isAnomaly      {boolean}  — is a fault scenario active?
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import './oracle.css';
import OracleHeader from './OracleHeader.jsx';
import SimulationProgressPanel from './SimulationProgressPanel.jsx';
import RankedActionsPanel from './RankedActionsPanel.jsx';
import OutcomeDistributionCard from './OutcomeDistributionCard.jsx';
import SocTrajectoryChart from './SocTrajectoryChart.jsx';
import SummaryMetricsCard from './SummaryMetricsCard.jsx';
import { createOracleSimulator } from './oracleAdapter.js';

// ─── Initial state ─────────────────────────────────────────────────────────
const INITIAL_STATE = {
  phase: 'DORMANT',   // 'DORMANT' | 'PROCESSING' | 'RESULT'
  progress: null,
  completedActions: [],
  winnerSummary: null,
  outcomeDistribution: null,
  socTrajectory: null,
};

// ─── Dormant view ─────────────────────────────────────────────────────────────
// No manual "trigger" button — this used to offer one that ran the offline
// fixture simulator even while genuinely connected to the backend, which
// meant a click while a real anomaly was mid-pipeline could silently swap
// in fabricated numbers indistinguishable from a real ORACLE run. ORACLE
// always auto-starts the moment the real oracle_simulation WS message
// arrives (see the useEffect below); there's no legitimate reason for a
// manual override that risks showing fake data as if it were real.
function DormantView({ isAnomaly, backendOnline }) {
  let msg = 'Awaiting proposed action(s) from ATHENA.';
  let subMsg = null;

  if (!isAnomaly) {
    msg = 'No anomaly detected.';
    subMsg = 'ORACLE will activate once SENTINEL flags a fault and SHERLOCK completes diagnosis.';
  } else if (backendOnline) {
    msg = 'Waiting for ORACLE simulation from backend…';
    subMsg = 'Simulation will begin automatically once SHERLOCK diagnosis is received.';
  } else {
    msg = 'Backend offline — no simulation available.';
    subMsg = 'ORACLE requires a live connection to backend/oracle/agent.py to run.';
  }

  return (
    <div className="oracle-dormant">
      <div className="oracle-dormant-icon">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" strokeWidth="1">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 2 C6 7 6 17 12 22" strokeWidth="0.8"/>
          <path d="M12 2 C18 7 18 17 12 22" strokeWidth="0.8"/>
          <line x1="2" y1="12" x2="22" y2="12" strokeWidth="0.8"/>
        </svg>
      </div>
      <div className="oracle-dormant-msg">{msg}</div>
      {subMsg && (
        <div className="oracle-dormant-sub">{subMsg}</div>
      )}
    </div>
  );
}

// ─── Result layout ────────────────────────────────────────────────────────────
function ResultView({ completedActions, winnerSummary, outcomeDistribution, socTrajectory }) {
  const [selectedActionName, setSelectedActionName] = useState(winnerSummary.actionName);

  // Derive data from the selected action, fallback to winner's default props if mock data is incomplete
  const selectedAction = completedActions.find(a => a.actionName === selectedActionName);
  const currentSummary = selectedAction?.summary || winnerSummary;
  const currentDistribution = selectedAction?.distribution || outcomeDistribution;
  const currentTrajectory = selectedAction?.trajectory || socTrajectory;

  const isSelectedWinner = selectedActionName === winnerSummary.actionName;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '14px 14px 20px' }}
    >
      {/* Full ranked table */}
      <RankedActionsPanel 
        actions={completedActions} 
        isPartial={false} 
        selectedActionName={selectedActionName}
        onActionSelect={setSelectedActionName}
      />

      {/* Selected action header row */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          letterSpacing: '0.22em',
          color: '#64748B',
          textTransform: 'uppercase',
          fontWeight: 700,
        }}>
          {isSelectedWinner ? 'WINNING ACTION:' : 'SELECTED ACTION:'}
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 14,
          fontWeight: 700,
          color: isSelectedWinner ? '#10B981' : '#3B82F6',
          letterSpacing: '0.04em',
        }}>
          {currentSummary.actionName}
        </span>
      </div>

      {/* Bottom row: distribution | SOC chart | metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1.45fr 1.1fr', gap: 14 }}>
        <div className="oracle-card">
          <OutcomeDistributionCard
            distribution={currentDistribution}
            actionName={currentSummary.actionName}
          />
        </div>

        <SocTrajectoryChart
          trajectory={currentTrajectory}
          stdFinalSoc={currentSummary.stdFinalSoc}
        />

        <SummaryMetricsCard summary={currentSummary} isWinner={isSelectedWinner} />
      </div>
    </motion.div>
  );
}

// ─── Main OracleView ──────────────────────────────────────────────────────────
export default function OracleView({ backendOnline = false, backendData = null, isAnomaly = false }) {
  const [state, setState] = useState(INITIAL_STATE);
  const simulatorRef = useRef(null);
  // Stable string key of the last oracle result we triggered on.
  // Using a string (not object reference) because backendData is rebuilt on
  // every WS telemetry packet, giving backendData?.oracle a new reference
  // even when oracle content hasn't changed.
  const lastOracleKeyRef = useRef(null);

  const handleUpdate = useCallback((update) => {
    setState(prev => ({
      ...prev,
      phase: update.state,
      progress: update.progress ?? prev.progress,
      completedActions: update.completedActions ?? prev.completedActions,
      winnerSummary: update.winnerSummary ?? prev.winnerSummary,
      outcomeDistribution: update.outcomeDistribution ?? prev.outcomeDistribution,
      socTrajectory: update.socTrajectory ?? prev.socTrajectory,
    }));
  }, []);

  // Keep a stable ref to handleUpdate so the simulator closure never goes stale
  const handleUpdateRef = useRef(handleUpdate);
  useEffect(() => { handleUpdateRef.current = handleUpdate; }, [handleUpdate]);

  // ── Kick off simulation ────────────────────────────────────────────────────
  // Returns a new simulator object (started). Caller owns cleanup.
  const launchSimulator = useCallback((backendMsg = null) => {
    // Stop any existing simulator first
    if (simulatorRef.current) {
      simulatorRef.current.stop();
      simulatorRef.current = null;
    }
    setState(INITIAL_STATE);
    const sim = createOracleSimulator(
      (update) => handleUpdateRef.current(update),
      backendMsg
    );
    simulatorRef.current = sim;
    sim.start();
    return sim;
  }, []);

  const launchSimulatorRef = useRef(launchSimulator);
  useEffect(() => { launchSimulatorRef.current = launchSimulator; }, [launchSimulator]);

  const stopSimulation = useCallback(() => {
    if (simulatorRef.current) {
      simulatorRef.current.stop();
      simulatorRef.current = null;
    }
  }, []);

  // ── Watch for backend oracle results ──────────────────────────────────────
  //
  // KEY DESIGN DECISIONS:
  //
  // 1. STRING KEY not object identity — App.jsx rebuilds backendData on every
  //    WS message (telemetry fires ~1/s), so backendData?.oracle gets a new
  //    object reference every second even though oracle content is unchanged.
  //    We compare by a stable string key to detect only genuinely new results.
  //
  // 2. NO CLEANUP RETURN — if we returned a cleanup that stops the simulator,
  //    every incoming telemetry packet would kill the running animation.
  //    Only the unmount-only effect ([] deps below) handles teardown.
  //
  useEffect(() => {
    const msg = backendData?.oracle;
    if (!msg || !msg.results?.length || msg.mode === 'failed') return;

    const key = `${msg.best_action}|${msg.top_score}|${msg.mode}`;
    if (key === lastOracleKeyRef.current) return; // same result, already running

    lastOracleKeyRef.current = key;
    launchSimulatorRef.current(msg);
    // NO cleanup return here — telemetry WS packets must not stop the timer
  }, [backendData?.oracle]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Reset when anomaly clears ─────────────────────────────────────────────
  useEffect(() => {
    if (!isAnomaly) {
      stopSimulation();
      setState(INITIAL_STATE);
      lastOracleKeyRef.current = null;
    }
  }, [isAnomaly, stopSimulation]);

  // ── Unmount-only cleanup ─────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (simulatorRef.current) simulatorRef.current.stop();
      lastOracleKeyRef.current = null;
    };
  }, []);

  const { phase, progress, completedActions, winnerSummary, outcomeDistribution, socTrajectory } = state;

  return (
    <div className="oracle-view">
      <OracleHeader
        state={phase}
        progress={progress}
        backendOnline={backendOnline}
        onStart={() => launchSimulatorRef.current(backendData?.oracle ?? null)}
        onStop={stopSimulation}
        onFastForward={() => simulatorRef.current?.fastForward()}
      />

      <AnimatePresence mode="wait">
        {phase === 'DORMANT' && (
          <motion.div
            key="dormant"
            style={{ flex: 1, display: 'flex' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <DormantView
              isAnomaly={isAnomaly}
              backendOnline={backendOnline}
            />
          </motion.div>
        )}

        {phase === 'PROCESSING' && progress && (
          <motion.div
            key="processing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <SimulationProgressPanel
              progress={progress}
              completedActions={completedActions}
            />
          </motion.div>
        )}

        {phase === 'RESULT' && winnerSummary && (
          <motion.div
            key="result"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35 }}
          >
            <ResultView
              completedActions={completedActions}
              winnerSummary={winnerSummary}
              outcomeDistribution={outcomeDistribution}
              socTrajectory={socTrajectory}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
