/**
 * ORACLE Mock Data Generator
 * ===========================
 * setInterval-based simulator standing in for the live WebSocket feed.
 * Drives state: DORMANT -> PROCESSING -> RESULT
 */

// ─── Fixture: 6 candidate actions with realistic spread ──────────────────────
function _buildDist(nomCount, degCount, lossCount) {
  return { nominal: nomCount, degraded: degCount, missionLoss: lossCount, totalRuns: 100 };
}

function _buildTrajectory(meanFinalSoc, stdFinalSoc) {
  const pts = [];
  for (let t = 0; t <= 60; t += 2) {
    const progress = t / 60;
    const mean = 15 + (meanFinalSoc - 15) * (1 - Math.exp(-3 * progress)) + Math.sin(progress * 2) * 2;
    const std = (stdFinalSoc - 1) * Math.pow(progress, 1.5) + 1;
    pts.push({ timeMinutes: t, meanSoc: Math.min(100, Math.max(0, Math.round(mean * 10) / 10)), stdSoc: Math.round(std * 10) / 10 });
  }
  return pts;
}

function _buildSummary(a, rank) {
  const meanTTR = parseFloat((10 + (1 - Math.min(a.safetyScore, 1)) * 40).toFixed(1));
  return {
    actionName: a.actionName,
    safetyScore: a.safetyScore,
    successProbability: a.successProbability,
    meanFinalSoc: parseFloat((15 + a.nominalRecoveryRate * 65).toFixed(1)),
    stdFinalSoc: parseFloat((2 + a.missionLossRate * 12).toFixed(1)),
    meanTimeToRecoveryMin: meanTTR,
    p90TimeToRecoveryMin: parseFloat((meanTTR * 1.55).toFixed(1)),
    missionLossProbability: a.missionLossRate,
    whyItWon: {
      decidingLevel: rank === 1 ? 'primary' : 'secondary',
      explanation: rank === 1
        ? `Highest Safety Score (Primary). safety_score=${a.safetyScore.toFixed(3)}, nominal_recovery=${Math.round(a.nominalRecoveryRate * 100)}%.`
        : `Ranked #${rank} by safety score (${a.safetyScore.toFixed(3)}). Nominal recovery: ${Math.round(a.nominalRecoveryRate * 100)}%.`,
    },
  };
}

const _RAW_ACTIONS = [
  { actionName: 'switch_redundant_power_bus', safetyScore: 0.874, successProbability: 0.86, missionLossRate: 0.04, stdFinalBatterySoc: 0.041, nominalRecoveryRate: 0.86, degradedRate: 0.10, missionLossCount: 4, nominalCount: 86, degradedCount: 10 },
  { actionName: 'shed_nonessential_load', safetyScore: 0.792, successProbability: 0.78, missionLossRate: 0.07, stdFinalBatterySoc: 0.055, nominalRecoveryRate: 0.78, degradedRate: 0.15, missionLossCount: 7, nominalCount: 78, degradedCount: 15 },
  { actionName: 'reorient_max_solar_exposure', safetyScore: 0.651, successProbability: 0.64, missionLossRate: 0.12, stdFinalBatterySoc: 0.072, nominalRecoveryRate: 0.64, degradedRate: 0.24, missionLossCount: 12, nominalCount: 64, degradedCount: 24 },
  { actionName: 'activate_backup_heater', safetyScore: 0.441, successProbability: 0.43, missionLossRate: 0.14, stdFinalBatterySoc: 0.091, nominalRecoveryRate: 0.43, degradedRate: 0.43, missionLossCount: 14, nominalCount: 43, degradedCount: 43 },
  { actionName: 'enter_safe_low_power_mode', safetyScore: 0.297, successProbability: 0.28, missionLossRate: 0.32, stdFinalBatterySoc: 0.118, nominalRecoveryRate: 0.28, degradedRate: 0.40, missionLossCount: 32, nominalCount: 28, degradedCount: 40 },
  { actionName: 'thruster_isolation', safetyScore: 0.118, successProbability: 0.11, missionLossRate: 0.51, stdFinalBatterySoc: 0.195, nominalRecoveryRate: 0.11, degradedRate: 0.38, missionLossCount: 51, nominalCount: 11, degradedCount: 38 },
];

export const CANDIDATE_ACTIONS = _RAW_ACTIONS.map((a, i) => {
  const meanSoc = parseFloat((15 + a.nominalRecoveryRate * 65).toFixed(1));
  const stdSoc = parseFloat((2 + a.missionLossRate * 12).toFixed(1));
  return {
    ...a,
    rank: i + 1,
    summary: _buildSummary(a, i + 1),
    distribution: _buildDist(a.nominalCount, a.degradedCount, a.missionLossCount),
    trajectory: _buildTrajectory(meanSoc, stdSoc),
  };
});



// ─── SOC Trajectory fixture for winner ───────────────────────────────────────
export function generateSocTrajectory() {
  const points = [];
  for (let t = 0; t <= 60; t += 2) {
    const progress = t / 60;
    const meanSoc = 15 + 58 * (1 - Math.exp(-3 * progress)) + Math.sin(progress * 2) * 2;
    const stdSoc = 6.8 * (1 - 0.5 * progress) + 1;
    points.push({
      timeMinutes: t,
      meanSoc: Math.min(100, Math.max(0, Math.round(meanSoc * 10) / 10)),
      stdSoc: Math.round(stdSoc * 10) / 10,
    });
  }
  return points;
}

// ─── Winner summary fixture ───────────────────────────────────────────────────
export const WINNER_SUMMARY = {
  actionName: 'switch_redundant_power_bus',
  safetyScore: 0.874,
  successProbability: 0.86,
  meanFinalSoc: 71.3,
  stdFinalSoc: 6.8,
  meanTimeToRecoveryMin: 27.4,
  p90TimeToRecoveryMin: 42.1,
  missionLossProbability: 0.04,
  whyItWon: {
    decidingLevel: 'primary',
    explanation:
      'Highest Safety Score (Primary). No ties at primary level, so secondary and tertiary tiebreakers not required.',
  },
};

export const OUTCOME_DISTRIBUTION = {
  nominal: 86,
  degraded: 12,
  missionLoss: 2,
  totalRuns: 100,
};

// ─── Simulator factory ────────────────────────────────────────────────────────
const RUNS_PER_ACTION = 100;
const TICK_MS = 80; // speed of mock sim tick

export function createOracleSimulator(onUpdate) {
  let timer = null;
  let actionIdx = 0;
  let runIdx = 0;
  let runLog = [];
  let completedActions = [];
  let stopped = false;

  // Timing: track real timestamps to compute per-run duration
  let runTimestamps = []; // UTC string timestamps of completed runs

  function tick() {
    if (stopped) return;
    runIdx++;

    const nowUtc = new Date().toISOString();
    runTimestamps.push({ ts: Date.now(), runNumber: runIdx + actionIdx * RUNS_PER_ACTION });

    runLog = [
      { runNumber: runIdx, timestampUtc: nowUtc, completed: true },
      ...runLog,
    ].slice(0, 12);

    // Compute measured sec/run from real timestamps (only after 3+ runs)
    let measuredSecPerRun = null;
    if (runTimestamps.length >= 3) {
      const recent = runTimestamps.slice(-5);
      const span = (recent[recent.length - 1].ts - recent[0].ts) / 1000;
      measuredSecPerRun = span / (recent.length - 1);
    }

    const totalCompleted = actionIdx * RUNS_PER_ACTION + runIdx;
    const totalRuns = CANDIDATE_ACTIONS.length * RUNS_PER_ACTION;

    if (runIdx >= RUNS_PER_ACTION) {
      // Action finished — score it and add to table
      const action = CANDIDATE_ACTIONS[actionIdx];
      completedActions = [
        ...completedActions,
        { ...action, rank: actionIdx + 1 },
      ];

      runIdx = 0;
      runTimestamps = [];
      actionIdx++;

      if (actionIdx >= CANDIDATE_ACTIONS.length) {
        // All done — emit RESULT state
        onUpdate({
          state: 'RESULT',
          progress: {
            currentActionIndex: CANDIDATE_ACTIONS.length,
            totalActions: CANDIDATE_ACTIONS.length,
            currentActionName: CANDIDATE_ACTIONS[CANDIDATE_ACTIONS.length - 1].actionName,
            currentRun: RUNS_PER_ACTION,
            totalRuns,
            runLog,
            measuredSecPerRun,
          },
          completedActions,
          winnerSummary: WINNER_SUMMARY,
          outcomeDistribution: OUTCOME_DISTRIBUTION,
          socTrajectory: generateSocTrajectory(),
        });
        clearInterval(timer);
        return;
      }
    }

    onUpdate({
      state: 'PROCESSING',
      progress: {
        currentActionIndex: actionIdx,
        totalActions: CANDIDATE_ACTIONS.length,
        currentActionName: CANDIDATE_ACTIONS[actionIdx].actionName,
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
      stopped = false;
      actionIdx = 0;
      runIdx = 0;
      runLog = [];
      completedActions = [];
      runTimestamps = [];

      onUpdate({
        state: 'PROCESSING',
        progress: {
          currentActionIndex: 0,
          totalActions: CANDIDATE_ACTIONS.length,
          currentActionName: CANDIDATE_ACTIONS[0].actionName,
          currentRun: 0,
          totalRuns: CANDIDATE_ACTIONS.length * RUNS_PER_ACTION,
          runLog: [],
          measuredSecPerRun: null,
        },
        completedActions: [],
      });

      timer = setInterval(tick, TICK_MS);
    },
    stop() {
      stopped = true;
      if (timer) clearInterval(timer);
    },
  };
}
