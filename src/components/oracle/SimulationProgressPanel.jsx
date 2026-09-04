import React from 'react';
import { motion } from 'motion/react';
import RankedActionsPanel from './RankedActionsPanel.jsx';
import { CANDIDATE_ACTIONS } from './oracleFixture.js';

function BatchStepper({ currentActionIndex, totalActions }) {
  return (
    <div>
      <div className="oracle-batch-stepper">
        {Array.from({ length: totalActions }).map((_, i) => {
          let cls = 'oracle-step oracle-step--pending';
          if (i < currentActionIndex) cls = 'oracle-step oracle-step--done';
          else if (i === currentActionIndex) cls = 'oracle-step oracle-step--active';
          return <div key={i} className={cls} />;
        })}
      </div>
      <div className="oracle-step-labels">
        <span>Action 1</span>
        <span>Action {Math.ceil(totalActions / 2)}</span>
        <span>Action {totalActions}</span>
      </div>
    </div>
  );
}

function MetaChip({ icon, value, label }) {
  return (
    <div className="oracle-meta-chip">
      <div className="oracle-meta-chip-icon">{icon}</div>
      <div className="oracle-meta-chip-val">{value}</div>
      <div className="oracle-meta-chip-lbl">{label}</div>
    </div>
  );
}

export default function SimulationProgressPanel({ progress, completedActions }) {
  const {
    currentActionIndex,
    totalActions,
    currentActionName,
    currentRun,
    totalRuns,
    runLog,
    measuredSecPerRun,
  } = progress;

  const actionPct = totalRuns > 0
    ? Math.round(((currentActionIndex * (totalRuns / totalActions) + currentRun) / totalRuns) * 100)
    : 0;

  const runPct = totalRuns > 0 ? (currentRun / (totalRuns / totalActions)) * 100 : 0;

  const estRemaining = measuredSecPerRun != null
    ? (() => {
        const runsLeft =
          (totalActions - currentActionIndex - 1) * (totalRuns / totalActions) +
          (totalRuns / totalActions - currentRun);
        const secLeft = runsLeft * measuredSecPerRun;
        const m = Math.floor(secLeft / 60);
        const s = Math.round(secLeft % 60);
        return `~${m}m ${s}s`;
      })()
    : null;

  const perRunStr = measuredSecPerRun != null
    ? `~${measuredSecPerRun.toFixed(1)} sec`
    : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '14px 14px 0' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 14 }}>
        {/* ── Left: current simulation progress ── */}
        <div className="oracle-card">
          <div className="oracle-card-title">CURRENT SIMULATION</div>

          <BatchStepper
            currentActionIndex={currentActionIndex}
            totalActions={totalActions}
          />

          <div className="oracle-current-action">
            Simulating {currentActionName}...
          </div>

          <div className="oracle-run-counter">
            Run {currentRun} <span>/ {totalRuns / totalActions}</span>
          </div>

          {/* per-action progress bar */}
          <div className="oracle-progress-track">
            <motion.div
              className="oracle-progress-fill"
              animate={{ width: `${runPct}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
              style={{ width: '0%' }}
            />
          </div>
          <div className="oracle-progress-pct">{Math.round(runPct)}%</div>

          {/* Meta chips */}
          <div className="oracle-sim-meta">
            <MetaChip icon="⬡" value={totalRuns / totalActions} label="Monte Carlo Runs" />
            <MetaChip icon="⟳" value="Sequential" label="Execution" />
            <MetaChip
              icon="⏱"
              value={perRunStr ?? '—'}
              label="Est. per Run"
            />
            <MetaChip
              icon="⏳"
              value={estRemaining ?? '—'}
              label="Est. Remaining"
            />
          </div>

          {/* Run log */}
          <div className="oracle-run-log-title">RUN LOG (LATEST)</div>
          <div className="oracle-run-log">
            {runLog.slice(0, 3).map((entry, i) => (
              <motion.div
                key={entry.runNumber}
                className="oracle-run-log-row"
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25 }}
              >
                <span style={{ color: '#64748B', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                  {entry.runNumber}
                </span>
                <span>{entry.timestampUtc.slice(11, 19)}</span>
                <span>
                  <span className="oracle-run-log-checkmark">✓</span>
                  {' '}Run completed
                </span>
              </motion.div>
            ))}
            {runLog.length > 3 && (
              <div className="oracle-run-log-row oracle-run-log-row--ellipsis">
                ... ...
              </div>
            )}
          </div>
        </div>

        {/* ── Right: live ranked table ── */}
        <RankedActionsPanel actions={completedActions} isPartial={true} />
      </div>
    </div>
  );
}
