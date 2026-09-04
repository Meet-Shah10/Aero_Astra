/**
 * ORACLE Tiebreak Unit Tests
 * Run with: npx vitest run src/components/oracle/tiebreak.test.js
 */
import { describe, it, expect } from 'vitest';
import { computeDecidingLevel, computeAllDecidingLevels } from './tiebreak.js';

const makeRow = (safetyScore, missionLossRate, stdFinalBatterySoc, nominalRecoveryRate) => ({
  safetyScore, missionLossRate, stdFinalBatterySoc, nominalRecoveryRate,
});

describe('computeDecidingLevel', () => {
  it('rank 1 (no rowAbove) always returns primary', () => {
    const row = makeRow(0.87, 0.04, 0.041, 0.91);
    expect(computeDecidingLevel(row, null)).toBe('primary');
  });

  it('differs at primary (safetyScore different)', () => {
    const above = makeRow(0.87, 0.04, 0.041, 0.91);
    const row   = makeRow(0.74, 0.07, 0.055, 0.81);
    expect(computeDecidingLevel(row, above)).toBe('primary');
  });

  it('tie at primary -> decided at secondary (missionLossRate)', () => {
    const above = makeRow(0.70, 0.04, 0.041, 0.91);
    const row   = makeRow(0.70, 0.09, 0.041, 0.91);
    expect(computeDecidingLevel(row, above)).toBe('secondary');
  });

  it('tie at primary + secondary -> decided at tertiary (stdFinalBatterySoc)', () => {
    const above = makeRow(0.70, 0.07, 0.041, 0.91);
    const row   = makeRow(0.70, 0.07, 0.099, 0.91);
    expect(computeDecidingLevel(row, above)).toBe('tertiary');
  });

  it('tie at primary + secondary + tertiary -> quaternary (nominalRecoveryRate)', () => {
    const above = makeRow(0.70, 0.07, 0.041, 0.91);
    const row   = makeRow(0.70, 0.07, 0.041, 0.80);
    expect(computeDecidingLevel(row, above)).toBe('quaternary');
  });

  it('all four fields tied -> returns quaternary (exhausted)', () => {
    const above = makeRow(0.70, 0.07, 0.041, 0.91);
    const row   = makeRow(0.70, 0.07, 0.041, 0.91);
    expect(computeDecidingLevel(row, above)).toBe('quaternary');
  });
});

describe('computeAllDecidingLevels', () => {
  it('first row always primary, rest computed correctly', () => {
    const rows = [
      makeRow(0.87, 0.04, 0.041, 0.91),
      makeRow(0.74, 0.07, 0.055, 0.81),
      makeRow(0.61, 0.12, 0.072, 0.73),
    ];
    const levels = computeAllDecidingLevels(rows);
    expect(levels[0]).toBe('primary');
    expect(levels[1]).toBe('primary');
    expect(levels[2]).toBe('primary');
  });

  it('secondary tie-break scenario', () => {
    const rows = [
      makeRow(0.70, 0.04, 0.041, 0.91),
      makeRow(0.70, 0.09, 0.041, 0.91),
    ];
    const levels = computeAllDecidingLevels(rows);
    expect(levels[0]).toBe('primary');
    expect(levels[1]).toBe('secondary');
  });
});
