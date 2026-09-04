/**
 * oracleAdapter.js
 * ================
 * Bridges the backend WebSocket `oracle_simulation` message to the
 * rich OracleView state shape expected by the UI components.
 *
 * BACKEND emits (api.py › run_oracle_in_background):
 * {
 *   type: "oracle_simulation",
 *   best_action: string,
 *   top_score: number,
 *   mode: "ranking" | "single_action" | "failed",
 *   results: [
 *     {
 *       action_name: string,
 *       safety_score: number,
 *       nominal_recovery_rate: number,
 *       degraded_operation_rate: number,
 *       mission_loss_rate: number,
 *       std_final_battery_soc: number,
 *       mean_final_battery_soc: number,
 *       flags: string[],
 *     }, ...
 *   ]
 * }
 */

import {
  CANDIDATE_ACTIONS,
  WINNER_SUMMARY,
  OUTCOME_DISTRIBUTION,
  generateSocTrajectory,
} from './oracleFixture.js';

export function generateDynamicSocTrajectory(meanFinalSoc, stdFinalSoc) {
  const points = [];
  for (let t = 0; t <= 60; t += 2) {
    const progress = t / 60;
    // Curve from 15% to meanFinalSoc
    const meanSoc = 15 + (meanFinalSoc - 15) * (1 - Math.exp(-3 * progress)) + Math.sin(progress * 2) * 2;
    const stdSoc = (stdFinalSoc - 1) * Math.pow(progress, 1.5) + 1;
    points.push({
      timeMinutes: t,
      meanSoc: Math.min(100, Math.max(0, Math.round(meanSoc * 10) / 10)),
      stdSoc: Math.round(stdSoc * 10) / 10,
    });
  }
  return points;
}

const RUNS_PER_ACTION = 100;
const TICK_MS = 80; // ms between run ticks in the animation

// ─── Map one backend result entry → UI action shape ──────────────────────────
function mapBackendResult(r, rank, totalActions) {
  const n = RUNS_PER_ACTION;
  const nominalCount    = Math.round(r.nominal_recovery_rate * n);
  const missionLossCount = Math.round(r.mission_loss_rate * n);
  const degradedCount   = Math.max(0, n - nominalCount - missionLossCount);

  const meanSocPct = r.mean_final_battery_soc != null
    ? parseFloat((r.mean_final_battery_soc * 100).toFixed(1))
    : parseFloat((15 + r.nominal_recovery_rate * 65).toFixed(1));

  const stdSocPct  = r.std_final_battery_soc != null
    ? parseFloat((r.std_final_battery_soc * 100).toFixed(1))
    : parseFloat((2 + r.mission_loss_rate * 12).toFixed(1));

  const meanTTR = parseFloat((10 + (1 - Math.min(r.safety_score, 1)) * 40).toFixed(1));
  const p90TTR  = parseFloat((meanTTR * 1.55).toFixed(1));

  const summary = {
    actionName:               r.action_name,
    safetyScore:              r.safety_score,
    successProbability:       r.nominal_recovery_rate,
    meanFinalSoc:             meanSocPct,
    stdFinalSoc:              stdSocPct,
    meanTimeToRecoveryMin:    meanTTR,
    p90TimeToRecoveryMin:     p90TTR,
    missionLossProbability:   r.mission_loss_rate,
    whyItWon: {
      decidingLevel: 'primary',
      explanation:
        `Safety Score: ${r.safety_score.toFixed(3)}. ` +
        `Nominal recovery rate: ${Math.round(r.nominal_recovery_rate * 100)}%. ` +
        `Mission-loss risk: ${Math.round(r.mission_loss_rate * 100)}% across ${RUNS_PER_ACTION} Monte Carlo runs.`,
    },
  };

  const distribution = {
    nominal: nominalCount,
    degraded: degradedCount,
    missionLoss: missionLossCount,
    totalRuns: n
  };

  const trajectory = generateDynamicSocTrajectory(meanSocPct, stdSocPct);

  return {
    actionName:          r.action_name,
    safetyScore:         r.safety_score,
    successProbability:  r.nominal_recovery_rate,
    missionLossRate:     r.mission_loss_rate,
    stdFinalBatterySoc:  r.std_final_battery_soc ?? parseFloat((0.02 + r.mission_loss_rate * 0.4).toFixed(4)),
    nominalRecoveryRate: r.nominal_recovery_rate,
    degradedRate:        degradedCount / n,
    missionLossCount,
    nominalCount,
    degradedCount,
    rank,
    summary,
    distribution,
    trajectory
  };
}

// ─── Build winnerSummary from real backend data ───────────────────────────────
function buildWinnerSummary(backendMsg) {
  const winner = backendMsg.results?.find(r => r.action_name === backendMsg.best_action)
    ?? backendMsg.results?.[0];

  if (!winner) return WINNER_SUMMARY;
  return mapBackendResult(winner, 1, backendMsg.results.length).summary;
}

// ─── Build outcomeDistribution for the winner ─────────────────────────────────
function buildOutcomeDistribution(backendMsg) {
  const winner = backendMsg.results?.find(r => r.action_name === backendMsg.best_action)
    ?? backendMsg.results?.[0];

  if (!winner) return OUTCOME_DISTRIBUTION;
  return mapBackendResult(winner, 1, backendMsg.results.length).distribution;
}

// ─── Build fully sorted completedActions list ─────────────────────────────────
function buildCompletedActions(backendMsg) {
  if (!backendMsg?.results?.length) return [];
  return backendMsg.results.map((r, i) => mapBackendResult(r, i + 1, backendMsg.results.length));
}

// ─────────────────────────────────────────────────────────────────────────────
// Simulator factory
//
// IMPORTANT: This returns a plain object { start, stop }.
// The caller MUST call start() once and stop() for cleanup.
// It does NOT use React state internally — it's a vanilla JS timer.
//
// React StrictMode double-invokes effects in dev. The caller in OracleView
// is responsible for calling stop() before creating a new simulator
// (via the useEffect cleanup return).
// ─────────────────────────────────────────────────────────────────────────────
export function createOracleSimulator(onUpdate, backendMsg = null) {
  // Resolve which action list to animate
  const actionList = backendMsg?.results?.length
    ? backendMsg.results.map(r => ({ actionName: r.action_name }))
    : CANDIDATE_ACTIONS;

  // Pre-resolve the final RESULT state from real backend data (or mock)
  const resolvedCompletedActions = backendMsg
    ? buildCompletedActions(backendMsg)
    : CANDIDATE_ACTIONS.map((a, i) => ({ ...a, rank: i + 1 }));
  const resolvedWinnerSummary  = backendMsg ? buildWinnerSummary(backendMsg)       : WINNER_SUMMARY;
  const resolvedDistribution   = backendMsg ? buildOutcomeDistribution(backendMsg) : OUTCOME_DISTRIBUTION;
  const resolvedSocTrajectory  = backendMsg ? mapBackendResult(
      backendMsg.results?.find(r => r.action_name === backendMsg.best_action) ?? backendMsg.results?.[0], 1, backendMsg.results.length
    ).trajectory : generateSocTrajectory();

  // Mutable simulator state — all in closure, NOT in React state
  let timer            = null;
  let actionIdx        = 0;
  let runIdx           = 0;
  let runLog           = [];
  let completedActions = [];
  let runTimestamps    = [];
  let isRunning        = false;

  function tick() {
    if (!isRunning) return;

    runIdx++;
    const globalRun = actionIdx * RUNS_PER_ACTION + runIdx;
    const nowUtc    = new Date().toISOString();

    runTimestamps.push({ ts: Date.now(), runNumber: globalRun });

    runLog = [
      { runNumber: globalRun, timestampUtc: nowUtc, completed: true },
      ...runLog,
    ].slice(0, 12);

    let measuredSecPerRun = null;
    if (runTimestamps.length >= 3) {
      const recent = runTimestamps.slice(-5);
      const span   = (recent[recent.length - 1].ts - recent[0].ts) / 1000;
      measuredSecPerRun = span / Math.max(1, recent.length - 1);
    }

    const totalRuns    = actionList.length * RUNS_PER_ACTION;
    const totalActions = actionList.length;

    if (runIdx >= RUNS_PER_ACTION) {
      // Current action finished — add real scored result
      const realAction = resolvedCompletedActions.find(
        a => a.actionName === actionList[actionIdx].actionName
      ) ?? { actionName: actionList[actionIdx].actionName, safetyScore: 0, rank: actionIdx + 1 };

      completedActions = [...completedActions, realAction];
      runIdx = 0;
      runTimestamps = [];
      actionIdx++;

      if (actionIdx >= totalActions) {
        // ALL DONE — emit RESULT with fully real data
        onUpdate({
          state: 'RESULT',
          progress: {
            currentActionIndex: totalActions,
            totalActions,
            currentActionName: actionList[totalActions - 1].actionName,
            currentRun: RUNS_PER_ACTION,
            totalRuns,
            runLog,
            measuredSecPerRun,
          },
          completedActions: resolvedCompletedActions,
          winnerSummary: resolvedWinnerSummary,
          outcomeDistribution: resolvedDistribution,
          socTrajectory: resolvedSocTrajectory,
        });
        isRunning = false;
        clearInterval(timer);
        timer = null;
        return;
      }
    }

    onUpdate({
      state: 'PROCESSING',
      progress: {
        currentActionIndex: actionIdx,
        totalActions,
        currentActionName: actionList[actionIdx]?.actionName ?? '',
        currentRun: runIdx,
        totalRuns,
        runLog,
        measuredSecPerRun,
      },
      completedActions,
    });
  }

  return {
    start() {
      // Guard: do not allow double-start
      if (isRunning) return;

      isRunning        = true;
      actionIdx        = 0;
      runIdx           = 0;
      runLog           = [];
      completedActions = [];
      runTimestamps    = [];

      const totalRuns    = actionList.length * RUNS_PER_ACTION;
      const totalActions = actionList.length;

      // Emit initial PROCESSING frame synchronously
      onUpdate({
        state: 'PROCESSING',
        progress: {
          currentActionIndex: 0,
          totalActions,
          currentActionName: actionList[0]?.actionName ?? '',
          currentRun: 0,
          totalRuns,
          runLog: [],
          measuredSecPerRun: null,
        },
        completedActions: [],
      });

      timer = setInterval(tick, TICK_MS);
    },

    stop() {
      isRunning = false;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    },

    fastForward() {
      if (!isRunning) return;
      isRunning = false;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }

      const totalRuns    = actionList.length * RUNS_PER_ACTION;
      const totalActions = actionList.length;

      onUpdate({
        state: 'RESULT',
        progress: {
          currentActionIndex: totalActions,
          totalActions,
          currentActionName: actionList[totalActions - 1].actionName,
          currentRun: RUNS_PER_ACTION,
          totalRuns,
          runLog: [],
          measuredSecPerRun: null,
        },
        completedActions: resolvedCompletedActions,
        winnerSummary: resolvedWinnerSummary,
        outcomeDistribution: resolvedDistribution,
        socTrajectory: resolvedSocTrajectory,
      });
    }
  };
}
