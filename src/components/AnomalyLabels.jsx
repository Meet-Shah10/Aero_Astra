import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import './AnomalyLabels.css';

// Screen-space callout labels for the anomaly-locked camera pose. Anchor
// points (percent of the .center-view box) are eyeballed against the
// current ANOMALY_FOCUS camera framing in App.jsx — a rough first pass,
// not raycast against real mesh geometry. Re-tune these alongside
// ANOMALY_FOCUS if the camera framing changes.
const LABEL_SETS = {
  'TCS': {
    anchor: { x: 30, y: 58 },
    // Kept clear of .overlay-status ("ORACLE: DIGITAL TWIN LIVE"), which
    // occupies roughly x:1.5-28%, y:3-10% of this box.
    stack: { x: 24, y: 48 },
    labels: [
      { text: 'TCS', sub: 'Thermal Control' },
      { text: 'TEMP RISING', sub: '+4.2°C/hr' },
      { text: 'ANOMALY DETECTED', danger: true },
    ],
  },
  'TT&C': {
    anchor: { x: 54, y: 30 },
    stack: { x: 76, y: 24 },
    labels: [
      { text: 'TT&C', sub: 'Comm Dish' },
      { text: 'SIGNAL LOSS', sub: '-114.7 dBm' },
      { text: 'ANOMALY DETECTED', danger: true },
    ],
  },
  'ADCS': {
    anchor: { x: 54, y: 30 },
    stack: { x: 76, y: 24 },
    labels: [
      { text: 'ADCS', sub: 'Attitude Sensing' },
      { text: 'SENSOR DISAGREEMENT', sub: 'IRU vs. star tracker' },
      { text: 'ANOMALY DETECTED', danger: true },
    ],
  },
  'Propulsion': {
    anchor: { x: 50, y: 52 },
    stack: { x: 68, y: 66 },
    labels: [
      { text: 'PROPULSION', sub: 'Thruster' },
      { text: 'VALVE MISFIRE', sub: 'Uncontrolled torque' },
      { text: 'ANOMALY DETECTED', danger: true },
    ],
  },
  'EPS': {
    anchor: { x: 40, y: 62 },
    stack: { x: 24, y: 50 },
    labels: [
      { text: 'EPS', sub: 'Power Bus' },
      { text: 'LOAD CASCADE', sub: null },
      { text: 'ANOMALY DETECTED', danger: true },
    ],
  },
};

export default function AnomalyLabels({ subsystem, active, scenarioKey }) {
  const config = active ? LABEL_SETS[subsystem] : null;

  return (
    <AnimatePresence>
      {config && (
        <motion.div
          key={scenarioKey || subsystem}
          className="anomaly-labels"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
        >
          <svg className="anomaly-labels-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            <line
              x1={config.anchor.x} y1={config.anchor.y}
              x2={config.stack.x} y2={config.stack.y}
              className="anomaly-labels-line"
            />
          </svg>

          <div
            className="anomaly-labels-anchor"
            style={{ left: `${config.anchor.x}%`, top: `${config.anchor.y}%` }}
          >
            <span className="anomaly-labels-anchor-ping" />
          </div>

          <div
            className="anomaly-labels-stack"
            style={{ left: `${config.stack.x}%`, top: `${config.stack.y}%` }}
          >
            {config.labels.map((label, i) => (
              <motion.div
                key={label.text}
                className={`anomaly-label-chip${label.danger ? ' anomaly-label-chip--danger' : ''}`}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.25, delay: i * 0.12 }}
              >
                <span className="anomaly-label-chip-text">{label.text}</span>
                {label.sub && <span className="anomaly-label-chip-sub">{label.sub}</span>}
              </motion.div>
            ))}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
