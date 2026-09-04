import React from "react";
import { motion } from "motion/react";

export default function OutcomeDistributionCard({ distribution, actionName }) {
  const { nominal, degraded, missionLoss, totalRuns } = distribution;
  const nomPct  = Math.round((nominal     / totalRuns) * 100);
  const degPct  = Math.round((degraded    / totalRuns) * 100);
  const lossPct = Math.round((missionLoss / totalRuns) * 100);

  let insightText = "shows a high probability of full recovery with minimal mission risk in this scenario.";
  if (lossPct > 50) {
    insightText = "carries significant mission loss risk and is highly unpredictable.";
  } else if (nomPct < 50) {
    insightText = "frequently results in degraded operation or mission loss.";
  } else if (nomPct < 80) {
    insightText = "offers a moderate chance of recovery, but with notable risk of degraded operation.";
  }

  return (
    <div className="oracle-dist-wrap">
      {/* Section title */}
      <div className="oracle-dist-title">
        OUTCOME DISTRIBUTION <span className="oracle-dist-title-sub">(over {totalRuns} runs)</span>
      </div>

      {/* ── Segmented bar — numbers live INSIDE each segment ── */}
      <div className="oracle-dist-bar-v2">
        {/* Nominal — green, large */}
        <motion.div
          className="oracle-dist-seg-v2 oracle-dist-seg-v2--nominal"
          initial={{ width: 0 }}
          animate={{ width: `${nomPct}%` }}
          transition={{ duration: 0.65, ease: "easeOut", delay: 0.05 }}
        >
          <span className="oracle-dist-seg-num">{nominal}</span>
        </motion.div>

        {/* Degraded — amber, medium */}
        <motion.div
          className="oracle-dist-seg-v2 oracle-dist-seg-v2--degraded"
          initial={{ width: 0 }}
          animate={{ width: `${degPct}%` }}
          transition={{ duration: 0.65, ease: "easeOut", delay: 0.22 }}
        >
          <span className="oracle-dist-seg-num">{degraded}</span>
        </motion.div>

        {/* Mission Loss — red, small */}
        <motion.div
          className="oracle-dist-seg-v2 oracle-dist-seg-v2--loss"
          initial={{ width: 0 }}
          animate={{ width: `${lossPct}%` }}
          transition={{ duration: 0.65, ease: "easeOut", delay: 0.38 }}
        >
          <span className="oracle-dist-seg-num">{missionLoss}</span>
        </motion.div>
      </div>

      {/* ── Three-column legend ── */}
      <div className="oracle-dist-legend-v2">
        {/* Nominal */}
        <div className="oracle-dist-leg-col">
          <div className="oracle-dist-leg-header">
            <span className="oracle-dist-leg-swatch oracle-dist-leg-swatch--nominal" />
            <span className="oracle-dist-leg-name oracle-dist-leg-name--nominal">Nominal</span>
          </div>
          <div className="oracle-dist-leg-count">{nominal} ({nomPct}%)</div>
          <div className="oracle-dist-leg-desc">Recovered to full nominal operations</div>
        </div>

        {/* Degraded */}
        <div className="oracle-dist-leg-col">
          <div className="oracle-dist-leg-header">
            <span className="oracle-dist-leg-swatch oracle-dist-leg-swatch--degraded" />
            <span className="oracle-dist-leg-name oracle-dist-leg-name--degraded">Degraded</span>
          </div>
          <div className="oracle-dist-leg-count">{degraded} ({degPct}%)</div>
          <div className="oracle-dist-leg-desc">Recovered with some operational limits</div>
        </div>

        {/* Mission Loss */}
        <div className="oracle-dist-leg-col">
          <div className="oracle-dist-leg-header">
            <span className="oracle-dist-leg-swatch oracle-dist-leg-swatch--loss" />
            <span className="oracle-dist-leg-name oracle-dist-leg-name--loss">Mission Loss</span>
          </div>
          <div className="oracle-dist-leg-count">{missionLoss} ({lossPct}%)</div>
          <div className="oracle-dist-leg-desc">Mission could not be recovered</div>
        </div>
      </div>

      {/* ── Insight line ── */}
      <div className="oracle-dist-insight">
        <span className="oracle-dist-insight-icon">ⓘ</span>
        <span>
          The <strong style={{ color: "rgba(255,255,255,0.8)" }}>{actionName}</strong> action {insightText}
        </span>
      </div>
    </div>
  );
}
