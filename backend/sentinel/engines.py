import numpy as np
import pandas as pd
from pathlib import Path
import joblib
import logging

from .utils import extract_rolling_features

log = logging.getLogger("ENGINES")

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

# -----------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# -----------------------------------------------------------------------------
# Cache the loaded XGBoost model
_xgb_model = None

def _get_xgb_model():
    global _xgb_model
    if _xgb_model is None:
        model_path = MODELS_DIR / "sentinel_production.pkl"
        if model_path.exists():
            _xgb_model = joblib.load(model_path)
        else:
            log.warning(f"XGB model not found at {model_path}. Engine A will return 0.")
    return _xgb_model

def sigmoid_normalize(value, center, scale=1.0):
    """Normalize a value to [0,1] using a sigmoid centered at the threshold."""
    return 1.0 / (1.0 + np.exp(-(value - center) * scale))


# -----------------------------------------------------------------------------
# ENGINE A: XGBoost Flatline Detector & Persistence Filter
# -----------------------------------------------------------------------------
class SentinelPersistenceFilter:
    def __init__(self, threshold=0.60, min_consecutive_steps=35):
        self.threshold = threshold
        self.min_consecutive_steps = min_consecutive_steps
        self.counter = 0
        
    def update(self, score):
        if score >= self.threshold:
            self.counter += 1
        else:
            self.counter = 0
        return self.counter >= self.min_consecutive_steps

def score_xgboost(window_df, channel):
    """Run existing XGBoost flatline detector on a window."""
    model = _get_xgb_model()
    if model is None or window_df.empty:
        return 0.0, None
    
    if len(window_df) < 20:
        return 0.0, None
    
    if channel in window_df.columns:
        vals = window_df[channel].values
    elif 'value' in window_df.columns:
        vals = window_df['value'].values
    else:
        vals = window_df.iloc[:, 0].values
        
    format_df = pd.DataFrame({
        'segment': np.zeros(len(window_df), dtype=int),
        'value': vals
    })
        
    feats_df = extract_rolling_features(format_df, window_size=20)
    feature_cols = ['flatline_duration', 'log_inv_std']
    if feats_df.empty:
        return 0.0, None
        
    X = feats_df[feature_cols].values
    scores = model.predict_proba(X)[:, 1]
    
    warmup = 19
    if len(scores) > warmup:
        valid_scores = scores[warmup:]
        valid_X = X[warmup:]
    else:
        valid_scores = scores
        valid_X = X
    
    max_idx = np.argmax(valid_scores)
    max_score = float(valid_scores[max_idx])
    
    diagnostic_features = {
        'flatline_duration': float(valid_X[max_idx, 0]),
        'log_inv_std': float(valid_X[max_idx, 1])
    }
    
    return max_score, diagnostic_features


# -----------------------------------------------------------------------------
# ENGINE B: Spike & Boundary Detector
# -----------------------------------------------------------------------------
def score_physics_spike(current_window_df, static_mad_dict, mad_multiplier=4.0):
    """
    Detects physical spikes via Impulse Reversal + Single-Channel Isolation.
    Requires exactly 1 of the 3 magnetometer channels to flag a violation.
    """
    triad = ['CADC0872', 'CADC0873', 'CADC0874']
    
    # Check if triad is present in the dataframe
    if not all(ch in current_window_df.columns for ch in triad):
        return False, None
        
    violations = 0
    for ch in triad:
        vals = current_window_df[ch].values
        
        # If any channel drops out (contains NaN at the end due to ffill limit), abort
        if len(vals) < 3 or pd.isna(vals[-1]) or pd.isna(vals[-2]) or pd.isna(vals[-3]):
            return False, None
            
        t_curr = vals[-1]
        t_prev = vals[-2]
        t_older = vals[-3]
        
        dx_in = t_prev - t_older
        dx_out = t_curr - t_prev
        
        static_mad = static_mad_dict.get(ch, 0.0)
        
        cond_in = abs(dx_in) > mad_multiplier * static_mad
        cond_rev = (dx_in * dx_out < 0)
        cond_out = abs(dx_out) > mad_multiplier * static_mad
        
        if cond_in and cond_rev and cond_out:
            violations += 1
            
    # Single-Channel Isolation
    if violations == 1:
        return True, "physics_spike"
    
    return False, None


# -----------------------------------------------------------------------------
# ENGINE C: Correlation Shift Detector (DORMANT)
# -----------------------------------------------------------------------------
# Dormant per user request


# -----------------------------------------------------------------------------
# COMBINED PIPELINE
# -----------------------------------------------------------------------------
def score_telemetry_window(channel, current_window_df, persistence_filter, static_mad_dict, mad_multiplier):
    """
    Hybrid anomaly detector combining XGBoost (Engine A) and Spike/Boundary (Engine B).
    """
    # 1. Engine A (XGBoost + Persistence)
    xgb_score, xgb_diag = score_xgboost(current_window_df, channel)
    alarm_flatline = persistence_filter.update(xgb_score)
    
    # 2. Engine B (Physics Spike + Triad Isolation)
    alarm_spike, spike_method = score_physics_spike(
        current_window_df, static_mad_dict, mad_multiplier
    )
    
    # 3. Engine C (Dormant)
    alarm_correlation = False
    
    # Combine
    is_anomaly = alarm_flatline or alarm_spike
    
    triggered = "NONE"
    if is_anomaly:
        if alarm_spike:
            triggered = "ENGINE_B"
        elif alarm_flatline:
            triggered = "ENGINE_A"
            
    return {
        "channel": channel,
        "xgb_score": float(xgb_score),
        "xgb_diag": xgb_diag,
        "alarm_flatline": alarm_flatline,
        "alarm_spike": alarm_spike,
        "spike_method": spike_method,
        "is_anomaly": is_anomaly,
        "triggered_engine": triggered,
        "flagged_subsystem": "ADCS"
    }
