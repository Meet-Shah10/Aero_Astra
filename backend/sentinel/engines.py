import numpy as np
import pandas as pd
from pathlib import Path
import joblib
import logging
from collections import deque

from .utils import extract_rolling_features

log = logging.getLogger("ENGINES")

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

# -----------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# -----------------------------------------------------------------------------
# Cache the loaded XGBoost model
_xgb_model = None

def _is_lfs_pointer(path: Path) -> bool:
    """Return True if the file is a Git LFS pointer stub (plain-text, <512 bytes)."""
    try:
        if path.stat().st_size > 512:
            return False
        header = path.read_bytes()[:40].decode("utf-8", errors="ignore")
        return header.startswith("version https://git-lfs.github.com")
    except Exception:
        return False

def _get_xgb_model():
    global _xgb_model
    if _xgb_model is None:
        model_path = MODELS_DIR / "sentinel_production.pkl"
        if not model_path.exists():
            log.warning(f"XGB model not found at {model_path}. Engine A will return 0. "
                        "Run: cd backend/sentinel && python train.py")
        elif _is_lfs_pointer(model_path):
            raise RuntimeError(
                f"Model file at {model_path} is a Git LFS pointer stub, not a real model.\n"
                "To fix: cd backend/sentinel && python train.py\n"
                "This regenerates sentinel_production.pkl from the raw OPSSAT data."
            )
        else:
            _xgb_model = joblib.load(model_path)
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


class PhysicsSpikeFilter:
    def __init__(self, window_size=10, min_spikes_required=2):
        self.window_size = window_size
        self.min_spikes_required = min_spikes_required
        self.spike_history = deque()
        self.current_step = 0
        
    def reset(self):
        self.spike_history.clear()
        self.current_step = 0
        
    def update(self, current_window_df, static_mad_dict, mad_multiplier=4.0):
        self.current_step += 1
        
        is_spike, method = score_physics_spike(current_window_df, static_mad_dict, mad_multiplier)
        
        if is_spike:
            self.spike_history.append(self.current_step)
            
        while self.spike_history and self.spike_history[0] <= self.current_step - self.window_size:
            self.spike_history.popleft()
            
        alarm = len(self.spike_history) >= self.min_spikes_required
        return alarm, method if alarm else None

# -----------------------------------------------------------------------------
# ENGINE C: Residual Correlation Detector
# -----------------------------------------------------------------------------
# Catches the failure class Engines A/B structurally can't: two coupled
# channels drifting together away from their own short-horizon forecast,
# neither one crossing an absolute threshold fast enough alone to trip a
# single-channel alarm. Modeled on JAXA's Hitomi/ASTRO-H (2016) loss —
# IRU vs. star-tracker disagreement drove commanded wheel torque against a
# rotation that wasn't happening, so wheel speed and attitude error moved
# together instead of the wheel's effort actually correcting the error.
#
# Each channel gets a one-step-ahead EWMA forecast; residual = actual -
# forecast. When both residuals exceed a z-score threshold in the same
# direction for several consecutive frames, that's a correlated break, not
# independent per-channel noise.
#
# z_threshold=3.0 (was 2.0): recalibrated after noise.py raised attitude_error
# process noise 5x (0.04->0.2) and battery_soc noise 8x (0.0005->0.004) for
# ORACLE's Monte Carlo spread — at the old threshold this pushed nominal
# false-positive rate to 30% (measured over 20 seeds). At 3.0 it's back to
# 0/20 while still catching both adcs_sensor_fusion_failure and
# adcs_reaction_wheel_degradation within ~2-3s of onset.
class ResidualCorrelationDetector:
    def __init__(self, window=15, ewma_alpha=0.3, z_threshold=3.0, min_consecutive=5):
        self.window = window
        self.alpha = ewma_alpha
        self.z_threshold = z_threshold
        self.min_consecutive = min_consecutive
        self._err_pred = None
        self._wheel_pred = None
        self._err_resid_hist = deque(maxlen=window)
        self._wheel_resid_hist = deque(maxlen=window)
        self._consecutive = 0

    def update(self, attitude_error: float, wheel_speed: float):
        """
        Returns (alarm, err_actual, err_predicted, wheel_actual, wheel_predicted).
        Predicted values are the EWMA forecast made *before* seeing this
        sample — i.e. what Engine C expected this frame to look like.
        """
        if self._err_pred is None:
            self._err_pred = attitude_error
            self._wheel_pred = wheel_speed

        err_pred = self._err_pred
        wheel_pred = self._wheel_pred

        err_residual = attitude_error - err_pred
        wheel_residual = wheel_speed - wheel_pred

        self._err_resid_hist.append(err_residual)
        self._wheel_resid_hist.append(wheel_residual)

        # Update forecasts for the *next* frame.
        self._err_pred = self.alpha * attitude_error + (1 - self.alpha) * err_pred
        self._wheel_pred = self.alpha * wheel_speed + (1 - self.alpha) * wheel_pred

        alarm = False
        if len(self._err_resid_hist) == self.window:
            err_std = max(float(np.std(self._err_resid_hist)), 1e-6)
            wheel_std = max(float(np.std(self._wheel_resid_hist)), 1e-6)
            err_z = err_residual / err_std
            wheel_z = wheel_residual / wheel_std

            # Wheel speed is expected to trend down under normal control
            # effort, so a rising attitude error alongside an unusually
            # sharp wheel-speed *drop* (either sign break beyond its own
            # recent noise band) is the correlated-divergence signature.
            correlated_break = err_z > self.z_threshold and abs(wheel_z) > self.z_threshold
            self._consecutive = self._consecutive + 1 if correlated_break else 0
            alarm = self._consecutive >= self.min_consecutive

        return alarm, attitude_error, err_pred, wheel_speed, wheel_pred


# -----------------------------------------------------------------------------
# COMBINED PIPELINE
# -----------------------------------------------------------------------------
def score_telemetry_window(channel, current_window_df, persistence_filter, physics_filter, static_mad_dict, mad_multiplier):
    """
    Hybrid anomaly detector combining XGBoost (Engine A) and Spike/Boundary (Engine B).
    """
    # 1. Engine A (XGBoost + Persistence)
    xgb_score, xgb_diag = score_xgboost(current_window_df, channel)
    alarm_flatline = persistence_filter.update(xgb_score)
    
    # 2. Engine B (Physics Spike + Triad Isolation)
    alarm_spike, spike_method = physics_filter.update(
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
