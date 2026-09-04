/**
 * ORACLE — Tiebreak Diffing Logic
 * ================================
 * Pure functions: no React, no DOM dependency — fully unit-testable.
 *
 * Tiebreak order (mirrors backend scoring.py ranking_sort_key):
 *   1. safetyScore           DESC  -> "primary"
 *   2. missionLossRate       ASC   -> "secondary"
 *   3. stdFinalBatterySoc    ASC   -> "tertiary"
 *   4. nominalRecoveryRate   DESC  -> "quaternary"
 */

export const TIEBREAK_EPSILON = 1e-6;

export const DECIDING_LEVELS = ['primary', 'secondary', 'tertiary', 'quaternary'];

/**
 * Returns which tiebreak level first differentiates `row` from `rowAbove`.
 * If rowAbove is null (rank 1), always returns 'primary'.
 * If all 4 fields tie within epsilon, returns 'quaternary'.
 */
export function computeDecidingLevel(row, rowAbove) {
  if (!rowAbove) return 'primary';

  if (Math.abs(row.safetyScore - rowAbove.safetyScore) > TIEBREAK_EPSILON) {
    return 'primary';
  }
  if (Math.abs(row.missionLossRate - rowAbove.missionLossRate) > TIEBREAK_EPSILON) {
    return 'secondary';
  }
  if (Math.abs(row.stdFinalBatterySoc - rowAbove.stdFinalBatterySoc) > TIEBREAK_EPSILON) {
    return 'tertiary';
  }
  return 'quaternary';
}

/**
 * Map deciding levels across an entire ranked array.
 * Index 0 (rank 1) always gets 'primary'.
 */
export function computeAllDecidingLevels(rankedRows) {
  return rankedRows.map((row, i) =>
    computeDecidingLevel(row, i === 0 ? null : rankedRows[i - 1])
  );
}

export const LEVEL_LABELS = {
  primary:    'Primary: Safety Score',
  secondary:  'Secondary: Mission Loss',
  tertiary:   'Tertiary: SOC Variance',
  quaternary: 'Quaternary: Nominal Rate',
};

export function decidingLevelBadge(level, rank) {
  if (rank === 1) {
    return level === 'primary'
      ? 'Primary: Highest Safety Score (No tie)'
      : `Won at ${LEVEL_LABELS[level]}`;
  }
  return '—';
}
