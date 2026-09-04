import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { computeAllDecidingLevels, decidingLevelBadge } from './tiebreak.js';

/** Interpolate from red -> amber -> green based on score 0..1 */
function scoreColor(score) {
  if (score >= 0.7) return '#10B981';
  if (score >= 0.4) return '#F59E0B';
  return '#EF4444';
}

function SafetyBar({ score }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const color = scoreColor(score);
  return (
    <div>
      <div className="oracle-score-val" style={{ color }}>
        {score.toFixed(3)}
      </div>
      <div className="oracle-score-bar-track">
        <motion.div
          className="oracle-score-bar-fill"
          style={{ background: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}

export default function RankedActionsPanel({ actions = [], isPartial = false, selectedActionName, onActionSelect }) {
  const levels = computeAllDecidingLevels(actions);

  return (
    <div className="oracle-card oracle-ranked-panel">
      <div className="oracle-card-title">
        RESULTS {isPartial ? '(LIVE)' : ''} — RANKED BY SAFETY SCORE
      </div>

      <table className="oracle-ranked-table">
        <thead>
          <tr>
            <th style={{ width: 32 }}>RANK</th>
            <th>ACTION</th>
            <th>
              SAFETY SCORE
              <div style={{ fontSize: 8, opacity: 0.6, fontWeight: 400, marginTop: 1 }}>Higher is better</div>
            </th>
            <th style={{ textAlign: 'right', paddingRight: 16 }}>SUCCESS PROB.</th>
            <th>WHY IT WON / TIEBREAKER</th>
          </tr>
        </thead>
        <tbody>
          <AnimatePresence>
            {actions.map((action, i) => {
              const rank = i + 1;
              const isWinner = rank === 1;
              const isSelected = selectedActionName === action.actionName;
              const badge = isWinner ? decidingLevelBadge(levels[i], 1) : '—';

              return (
                <motion.tr
                  key={action.actionName}
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: i * 0.06 }}
                  onClick={() => onActionSelect && onActionSelect(action.actionName)}
                  style={{
                    cursor: onActionSelect ? 'pointer' : 'default',
                    background: isSelected 
                      ? 'rgba(59,130,246,0.1)'
                      : isWinner
                        ? 'rgba(16,185,129,0.05)'
                        : 'transparent',
                    boxShadow: isSelected ? 'inset 2px 0 0 #3B82F6' : 'none'
                  }}
                >
                  <td>
                    <span className={`oracle-rank-cell${isWinner ? ' oracle-rank-cell--winner' : ''}`}>
                      {isWinner ? '◉' : rank}
                    </span>
                  </td>

                  <td>
                    <div className="oracle-action-name-cell">
                      {action.actionName}
                      {isWinner && <span className="oracle-winner-badge">WINNER</span>}
                    </div>
                  </td>

                  <td className="oracle-score-cell">
                    <SafetyBar score={action.safetyScore} />
                  </td>

                  <td className="oracle-prob-cell" style={{ color: scoreColor(action.safetyScore) }}>
                    {Math.round(action.successProbability * 100)}%
                  </td>

                  <td className={`oracle-tiebreak-cell${isWinner ? ' oracle-tiebreak-cell--winner' : ''}`}>
                    {badge}
                  </td>
                </motion.tr>
              );
            })}
          </AnimatePresence>
        </tbody>
      </table>

      {/* Score gradient legend */}
      {actions.length > 0 && (
        <div className="oracle-score-legend">
          <span>Lower Safety</span>
          <div className="oracle-score-legend-bar" />
          <span>Higher Safety</span>
        </div>
      )}
    </div>
  );
}
