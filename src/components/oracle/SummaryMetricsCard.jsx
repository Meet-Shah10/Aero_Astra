import React from 'react';

function MetricRow({ label, value, color }) {
  return (
    <div className="oracle-metric-row">
      <span className="oracle-metric-label">{label}</span>
      <span className="oracle-metric-val" style={{ color: color ?? '#E2E8F0' }}>
        {value}
      </span>
    </div>
  );
}

export default function SummaryMetricsCard({ summary, isWinner }) {
  const {
    safetyScore,
    successProbability,
    meanFinalSoc,
    stdFinalSoc,
    meanTimeToRecoveryMin,
    p90TimeToRecoveryMin,
    missionLossProbability,
    whyItWon,
  } = summary;

  const lossPct  = Math.round(missionLossProbability * 100);
  const succPct  = Math.round(successProbability * 100);

  return (
    <div className="oracle-card">
      <div className="oracle-card-title">SUMMARY METRICS {isWinner ? '(WINNER)' : '(SELECTED)'}</div>

      <div className="oracle-metrics-grid">
        <MetricRow
          label="Safety Score (Primary)"
          value={safetyScore.toFixed(3)}
          color="#10B981"
        />
        <MetricRow
          label="Success Probability"
          value={`${succPct}%`}
          color="#10B981"
        />
        <MetricRow
          label="Mean Final Battery SOC"
          value={`${meanFinalSoc}%`}
          color="#E2E8F0"
        />
        <MetricRow
          label="Std Dev Final Battery SOC (Tertiary)"
          value={`${stdFinalSoc}%`}
          color="#F59E0B"
        />
        <MetricRow
          label="Mean Time to Recovery"
          value={`${meanTimeToRecoveryMin} min`}
          color="#E2E8F0"
        />
        <MetricRow
          label="Max Time to Recovery (90th pct)"
          value={`${p90TimeToRecoveryMin} min`}
          color="#E2E8F0"
        />
        <MetricRow
          label="Mission Loss Probability"
          value={`${lossPct}%`}
          color={lossPct > 10 ? '#EF4444' : '#10B981'}
        />
      </div>

      {/* WHY IT WON box */}
      <div className="oracle-why-box">
        <div className="oracle-why-title">ⓘ {isWinner ? 'WHY IT WON' : 'INSIGHT'}</div>
        <div className="oracle-why-text">
          {whyItWon?.explanation ?? '—'}
        </div>
      </div>
    </div>
  );
}
