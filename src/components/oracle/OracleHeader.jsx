import React, { useState, useEffect } from 'react';

function LiveClock() {
  const [t, setT] = useState(() => new Date().toISOString().slice(11, 19));
  useEffect(() => {
    const id = setInterval(() => setT(new Date().toISOString().slice(11, 19)), 1000);
    return () => clearInterval(id);
  }, []);
  return <>{t} UTC</>;
}

export default function OracleHeader({ state, progress, backendOnline = false, onStart, onStop, onFastForward }) {
  const isProcessing = state === 'PROCESSING';
  const isResult     = state === 'RESULT';

  const statusColor = isResult ? '#10B981' : isProcessing ? '#F59E0B' : '#64748B';
  const statusText  = isResult ? 'STATUS: COMPLETE' : isProcessing ? 'STATUS: PROCESSING' : 'STATUS: DORMANT';
  const dotClass    = `oracle-status-dot oracle-status-dot--${state.toLowerCase()}`;

  const totalDone = progress
    ? progress.currentActionIndex * progress.totalRuns / progress.totalActions + progress.currentRun
    : 0;

  return (
    <div className="oracle-header">
      {/* Left — logo + identity */}
      <div className="oracle-header-left">
        <div className="oracle-logo-box">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" strokeWidth="1.5">
            <circle cx="12" cy="12" r="9"/>
            <path d="M12 3 C6 8 6 16 12 21" strokeWidth="1.2"/>
            <path d="M12 3 C18 8 18 16 12 21" strokeWidth="1.2"/>
            <line x1="3" y1="12" x2="21" y2="12" strokeWidth="1.2"/>
          </svg>
        </div>
        <div>
          <div className="oracle-agent-code">ORACLE</div>
          <div className="oracle-agent-role">The Simulator</div>
        </div>
      </div>

      {/* Center — status */}
      <div className="oracle-header-center">
        <div className="oracle-status-badge" style={{ color: statusColor }}>
          <span className={dotClass} />
          {statusText}
        </div>
        <div className="oracle-status-time"><LiveClock /></div>
      </div>

      {/* Right — controls + ATHENA badge */}
      <div className="oracle-header-right">
        {(isProcessing || isResult) && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="oracle-sim-btn"
              onClick={isProcessing ? onStop : onStart}
            >
              {isProcessing ? (
                <>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                    <rect x="1" y="1" width="3" height="8"/>
                    <rect x="6" y="1" width="3" height="8"/>
                  </svg>
                  PAUSE SIMULATION
                </>
              ) : (
                <>↺ RESTART</>
              )}
            </button>
            {isProcessing && (
              <button
                className="oracle-sim-btn"
                style={{ borderColor: '#3B82F6', color: '#3B82F6' }}
                onClick={onFastForward}
              >
                ⏭ FAST FORWARD
              </button>
            )}
          </div>
        )}
        <div className="oracle-athena-badge">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700 }}>Input from ATHENA</div>
            <div style={{ fontSize: 9, opacity: 0.6 }}>6 candidate actions</div>
          </div>
        </div>
        {/* Backend connection indicator */}
        <div className={`oracle-backend-badge oracle-backend-badge--${backendOnline ? 'online' : 'offline'}`}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', display: 'inline-block' }} />
          {backendOnline ? 'BACKEND LIVE' : 'MOCK DATA'}
        </div>
      </div>
    </div>
  );
}
