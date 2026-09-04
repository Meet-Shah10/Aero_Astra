import React, { useState, useEffect, useMemo } from 'react';
import './VitalsCluster.css';

const HISTORY_LENGTH = 30;
const CRITICAL_THRESHOLD = 0.5;
const WARNING_THRESHOLD = 0.85;

// Helper to generate SVG path for sparkline
function generateSparkline(history) {
  if (!history || history.length < 2) return '';
  const max = 1;
  const min = 0;
  const width = 100; // SVG viewBox width
  const height = 20; // SVG viewBox height
  
  const stepX = width / (HISTORY_LENGTH - 1);
  const range = max - min;
  
  const points = history.map((val, i) => {
    const x = i * stepX;
    const y = height - ((val - min) / range) * height;
    return `${x},${y}`;
  });
  
  return `M ${points.join(' L ')}`;
}

// Reusable Gauge Component
function SubsystemGauge({ name, health, history }) {
  const isCritical = health < CRITICAL_THRESHOLD;
  const isWarning = health >= CRITICAL_THRESHOLD && health < WARNING_THRESHOLD;
  
  const statusClass = isCritical ? 'critical' : isWarning ? 'warning' : '';
  
  // Circle math for gauge
  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - health * circumference;

  return (
    <div className={`gauge-card ${statusClass}`}>
      <div className="gauge-title">{name}</div>
      
      <div className="gauge-svg-container">
        <svg viewBox="0 0 60 60" className="gauge-svg">
          <circle className="gauge-bg" cx="30" cy="30" r={radius} />
          <circle 
            className={`gauge-fill ${statusClass}`} 
            cx="30" 
            cy="30" 
            r={radius} 
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
          />
        </svg>
        <span className="gauge-value-text">
          {Math.round(health * 100)}%
        </span>
      </div>

      <div className="sparkline-container">
        <svg viewBox="0 0 100 20" preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
          <path 
            className={`sparkline-path ${statusClass}`} 
            d={generateSparkline(history)} 
          />
        </svg>
      </div>
    </div>
  );
}

export default function VitalsCluster({ vitals }) {
  // Safe default for when backend is offline or just starting
  const safeVitals = vitals || {
    worst_health: 1.0,
    eps_health: 1.0,
    tcs_health: 1.0,
    adcs_health: 1.0,
    ttc_health: 1.0
  };

  const [history, setHistory] = useState({
    eps: Array(HISTORY_LENGTH).fill(1),
    tcs: Array(HISTORY_LENGTH).fill(1),
    adcs: Array(HISTORY_LENGTH).fill(1),
    ttc: Array(HISTORY_LENGTH).fill(1),
  });

  // Calculate system health (average of all 4)
  const systemHealth = (safeVitals.eps_health + safeVitals.tcs_health + safeVitals.adcs_health + safeVitals.ttc_health) / 4;
  
  // Find the weakest subsystem name
  const weakestName = useMemo(() => {
    const keys = ['eps_health', 'tcs_health', 'adcs_health', 'ttc_health'];
    const worstKey = keys.reduce((a, b) => (safeVitals[a] ?? 1) <= (safeVitals[b] ?? 1) ? a : b);
    return worstKey.replace('_health', '').toUpperCase();
  }, [safeVitals]);

  // Determine worst health status for CSS classes
  const worstHealthValue = safeVitals.worst_health ?? 1.0;
  const isWorstCritical = worstHealthValue < CRITICAL_THRESHOLD;
  const isWorstWarning = worstHealthValue >= CRITICAL_THRESHOLD && worstHealthValue < WARNING_THRESHOLD;
  const worstStatusClass = isWorstCritical ? 'critical' : isWorstWarning ? 'warning' : '';

  // Update history on tick
  useEffect(() => {
    setHistory(prev => {
      const newEps = [...prev.eps.slice(1), safeVitals.eps_health ?? 1.0];
      const newTcs = [...prev.tcs.slice(1), safeVitals.tcs_health ?? 1.0];
      const newAdcs = [...prev.adcs.slice(1), safeVitals.adcs_health ?? 1.0];
      const newTtc = [...prev.ttc.slice(1), safeVitals.ttc_health ?? 1.0];
      return { eps: newEps, tcs: newTcs, adcs: newAdcs, ttc: newTtc };
    });
  }, [safeVitals.eps_health, safeVitals.tcs_health, safeVitals.adcs_health, safeVitals.ttc_health]);

  return (
    <div className="vitals-cluster">
      <div className="vitals-header">
        <div className="vitals-title-row">
          <span className="vitals-title">System Vitals</span>
          <div className="vitals-weakest">
            <span className={`worst-health-value ${worstStatusClass}`}>
              {Math.round(worstHealthValue * 100)}%
            </span>
          </div>
        </div>
        
        <div className="system-health-row">
          <span>Overall Average</span>
          <span className="system-health-value">
            {Math.round(systemHealth * 100)}%
          </span>
        </div>
        
        <div className="system-health-row" style={{ marginTop: '-4px' }}>
          <span>Weakest Subsystem</span>
          <span className={`weakest-subsystem-name ${worstStatusClass}`}>
            {weakestName}
          </span>
        </div>
      </div>

      <div className="vitals-grid">
        <SubsystemGauge 
          name="TCS" 
          health={safeVitals.tcs_health ?? 1.0} 
          history={history.tcs} 
        />
        <SubsystemGauge 
          name="EPS" 
          health={safeVitals.eps_health ?? 1.0} 
          history={history.eps} 
        />
        <SubsystemGauge 
          name="ADCS" 
          health={safeVitals.adcs_health ?? 1.0} 
          history={history.adcs} 
        />
        <SubsystemGauge 
          name="TT&C" 
          health={safeVitals.ttc_health ?? 1.0} 
          history={history.ttc} 
        />
      </div>
    </div>
  );
}
