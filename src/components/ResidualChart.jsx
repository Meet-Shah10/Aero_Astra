/* ResidualChart — plots actual vs. EWMA-predicted telemetry for a channel,
   shading the residual gap so the anomaly onset point is visually obvious.
   Consumes backend/api.py's 'residual_update' WS stream (Engine C). */

const W = 560;
const H = 90;
const PAD_L = 4;
const PAD_R = 4;

function buildPath(points, accessor, xScale, yScale) {
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(accessor(p))}`)
    .join(' ');
}

function ChannelTrack({ label, unit, points, actualOf, predOf, detectAtIndex, color }) {
  if (points.length < 2) return null;

  const actuals = points.map(actualOf);
  const preds = points.map(predOf);
  const all = [...actuals, ...preds];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;

  const xScale = (i) => PAD_L + (i / (points.length - 1)) * (W - PAD_L - PAD_R);
  const yScale = (v) => H - 4 - ((v - min) / range) * (H - 18);

  const actualPath = buildPath(points, actualOf, xScale, yScale);
  const predPath = buildPath(points, predOf, xScale, yScale);

  // Shaded band between actual and predicted — the residual itself.
  const bandPath = [
    ...points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(actualOf(p))}`),
    ...[...points].reverse().map((p, i) => `L ${xScale(points.length - 1 - i)} ${yScale(predOf(p))}`),
    'Z',
  ].join(' ');

  const detectX = detectAtIndex != null && detectAtIndex >= 0 && detectAtIndex < points.length
    ? xScale(detectAtIndex)
    : null;

  const latestActual = actuals[actuals.length - 1];
  const latestPred = preds[preds.length - 1];
  const residual = latestActual - latestPred;

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'rgba(255,255,255,0.5)', marginBottom: 2 }}>
        <span style={{ letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</span>
        <span>
          actual <strong style={{ color }}>{latestActual.toFixed(2)}{unit}</strong>
          {'  '}predicted {latestPred.toFixed(2)}{unit}
          {'  '}residual <strong style={{ color: Math.abs(residual) > 0.01 ? '#ff8080' : 'rgba(255,255,255,0.5)' }}>
            {residual >= 0 ? '+' : ''}{residual.toFixed(2)}
          </strong>
        </span>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', background: 'rgba(255,255,255,0.02)', borderRadius: 3 }}>
        <path d={bandPath} fill="rgba(255,128,128,0.12)" stroke="none" />
        <path d={predPath} fill="none" stroke="rgba(255,255,255,0.35)" strokeWidth="1" strokeDasharray="3 3" />
        <path d={actualPath} fill="none" stroke={color} strokeWidth="1.5" />
        {detectX != null && (
          <>
            <line x1={detectX} y1={0} x2={detectX} y2={H} stroke="#FFC168" strokeWidth="1" strokeDasharray="2 2" />
            <text x={detectX + 3} y={10} fontSize="7" fill="#FFC168">ANOMALY</text>
          </>
        )}
      </svg>
    </div>
  );
}

export default function ResidualChart({ residualHistory, detectTimestamp }) {
  if (!residualHistory || residualHistory.length < 5) {
    return (
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', padding: '8px 0' }}>
        Awaiting residual samples from Engine C (ADCS channels only)...
      </div>
    );
  }

  const detectAtIndex = detectTimestamp != null
    ? residualHistory.findIndex(p => p.timestamp >= detectTimestamp)
    : -1;

  return (
    <div>
      <ChannelTrack
        label="Attitude Error — actual vs. EWMA-predicted"
        unit="°"
        points={residualHistory}
        actualOf={p => p.attitude_error.actual}
        predOf={p => p.attitude_error.predicted}
        detectAtIndex={detectAtIndex}
        color="#7FE0FF"
      />
      <ChannelTrack
        label="Reaction Wheel Speed — actual vs. EWMA-predicted"
        unit=" rpm"
        points={residualHistory}
        actualOf={p => p.reaction_wheel_speed.actual}
        predOf={p => p.reaction_wheel_speed.predicted}
        detectAtIndex={detectAtIndex}
        color="#B39CFF"
      />
    </div>
  );
}
