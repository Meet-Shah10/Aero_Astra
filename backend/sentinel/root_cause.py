import os
import sys
import json
import logging
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix, average_precision_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

import xgboost as xgb
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import joblib
import shap
from .lstm import LSTMForecaster, extract_padded_sequences

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("SENTINEL")

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models" 
RESULTS_DIR = ROOT / "results"

from .utils import compute_run_length, extract_rolling_features

class RootCauseAnalyzer:
    def __init__(self):
        log.info("Initializing Root Cause Analyzer...")
        
        # Load XGBoost model
        self.xgb_path = ROOT / "models" / "sentinel_production.pkl"
        if not self.xgb_path.exists():
            log.error(f"XGBoost model not found at {self.xgb_path}")
            sys.exit(1)
        print('Loading XGB'); self.xgb_model = joblib.load(self.xgb_path)
        # Use TreeExplainer for XGBoost
        print('Loading Explainer'); self.explainer = shap.TreeExplainer(self.xgb_model)
        
        # Load LSTM model
        self.lstm_path = ROOT / "models" / "sentinel_lstm.pt"
        if not self.lstm_path.exists():
            log.error(f"LSTM model not found at {self.lstm_path}")
            sys.exit(1)
        self.device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
        print('Loading LSTM'); self.lstm_model = LSTMForecaster(input_dim=1, hidden_dim=64, num_layers=2, dropout=0.2)
        self.lstm_model.load_state_dict(torch.load(self.lstm_path, map_location=self.device))
        self.lstm_model = self.lstm_model.to(self.device)
        self.lstm_model.eval()
        
        # Load data
        print('Loading Data'); self.segments_df = pd.read_csv(ROOT / "data" / "raw" / "opssat" / "segments.csv")
        self.segments_df['timestamp_dt'] = pd.to_datetime(self.segments_df['timestamp'])
        self.segments_df.sort_values(by=['segment', 'timestamp_dt'], inplace=True)
        
        # Determine the scale for LSTM (using same naive scaler for simple relative residuals)
        from sklearn.preprocessing import MinMaxScaler
        self.scaler = MinMaxScaler()
        train_mask = self.segments_df['train'] == 1
        self.scaler.fit(self.segments_df.loc[train_mask, ['value']])
        
        # Static causal pattern mapping (Heuristic based on ADCS physics)
        # e.g. sun-sensor flatline -> degraded sun vector -> correlated shift in magnetometer axes
        self.CATS_PATTERNS = {
            "CADC0884": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD1 -> Mag X, Y, Z
            "CADC0886": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD2 -> Mag X, Y, Z
            "CADC0888": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD3 -> Mag X, Y, Z
            "CADC0890": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD4 -> Mag X, Y, Z
            "CADC0892": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD5 -> Mag X, Y, Z
            "CADC0894": ["CADC0872", "CADC0873", "CADC0874"], # Sun sensor PD6 -> Mag X, Y, Z
            "CADC0872": ["CADC0873", "CADC0874"],             # Mag X -> Mag Y, Z
            "CADC0873": ["CADC0872", "CADC0874"],             # Mag Y -> Mag X, Z
            "CADC0874": ["CADC0872", "CADC0873"],             # Mag Z -> Mag X, Y
        }
        
    def get_severity(self, score):
        if score >= 0.90:
            return "high"
        elif score >= 0.70:
            return "medium"
        elif score >= 0.5433:
            return "low"
        return "normal"

    def localize_onset(self, segment_df):
        """Use LSTM residual collapse to pinpoint flatline onset."""
        seg_data = segment_df['value'].values.reshape(-1, 1)
        seg_data_scaled = self.scaler.transform(seg_data).flatten()
        seqs, _ = extract_padded_sequences(seg_data_scaled, seq_len=10)
        
        if not seqs:
            return None
            
        with torch.no_grad():
            x_tensor = torch.tensor(np.array(seqs, dtype=np.float32)).unsqueeze(-1).to(self.device)
            preds_scaled = self.lstm_model(x_tensor).cpu().numpy().flatten()
            
        # Residuals collapse during a stuck sensor flatline
        residuals = np.abs(seg_data_scaled - preds_scaled)
        
        # Smooth residuals to find persistent flatlines
        smoothed_res = pd.Series(residuals).rolling(window=10, min_periods=1).mean().values
        
        # When residual drops extremely low (< 0.01 scaled error) and stays there, it's a flatline
        flatline_indices = np.where(smoothed_res < 0.01)[0]
        if len(flatline_indices) > 0:
            onset_idx = flatline_indices[0]
            return segment_df.iloc[onset_idx]['timestamp']
        
        # Fallback to just the highest variance drop point
        rolling_var = pd.Series(seg_data.flatten()).rolling(window=20, min_periods=1).var().fillna(method='bfill').values
        min_var_idx = np.argmin(rolling_var)
        return segment_df.iloc[min_var_idx]['timestamp']

    def analyze_segment(self, segment_id):
        # 1. Fetch Segment
        target_df = self.segments_df[self.segments_df['segment'] == segment_id].copy()
        if target_df.empty:
            log.error(f"Segment {segment_id} not found.")
            return None
            
        main_channel = target_df['channel'].iloc[0]
        
        # 2. Extract Features and get Max Score Row
        feats_df = extract_rolling_features(target_df, window_size=20)
        feature_cols = ['flatline_duration', 'log_inv_std']
        
        X_segment = feats_df[feature_cols].values
        scores = self.xgb_model.predict_proba(X_segment)[:, 1]
        
        max_idx = np.argmax(scores)
        max_score = float(scores[max_idx])
        
        if max_score < 0.5433:
            log.warning(f"Segment {segment_id} max score {max_score:.4f} is below anomaly threshold.")
        
        # 3. SHAP Attribution on peak row
        X_peak = X_segment[max_idx:max_idx+1]
        shap_values = self.explainer.shap_values(X_peak)[0]
        
        # Ensure it handles both binary classification outputs (sometimes 2D, sometimes 1D depending on shap version)
        if len(shap_values.shape) > 1 and shap_values.shape[1] == 2:
            shap_values = shap_values[:, 1]
            
        top_features = {
            "flatline_duration": float(shap_values[0]),
            "log_inv_std": float(shap_values[1])
        }
        
        # 4. Onset Localization
        onset_timestamp = self.localize_onset(target_df)
        
        # 5. Cross-Channel Context (Find related channels in the same time window)
        start_time = target_df['timestamp_dt'].min()
        end_time = target_df['timestamp_dt'].max()
        
        overlapping_df = self.segments_df[
            (self.segments_df['timestamp_dt'] >= start_time) &
            (self.segments_df['timestamp_dt'] <= end_time) &
            (self.segments_df['channel'] != main_channel)
        ].copy()
        
        related_channels = []
        if not overlapping_df.empty:
            for ch in overlapping_df['channel'].unique():
                ch_df = overlapping_df[overlapping_df['channel'] == ch].copy()
                if len(ch_df) < 20: continue # Skip if too little data
                
                ch_feats = extract_rolling_features(ch_df, window_size=20)
                ch_scores = self.xgb_model.predict_proba(ch_feats[feature_cols].values)[:, 1]
                ch_max = float(np.max(ch_scores))
                
                if ch_max >= 0.5433:  # Only report if it exceeds threshold
                    related_channels.append({"channel": ch, "score": ch_max})
                    
        # Sort by score descending
        related_channels.sort(key=lambda x: x["score"], reverse=True)
        
        # 6. CATS Heuristic Lookup
        plausible_root_cause = "Unknown"
        if main_channel in self.CATS_PATTERNS:
            expected_affected = set(self.CATS_PATTERNS[main_channel])
            actual_affected = {rc["channel"] for rc in related_channels}
            if expected_affected.intersection(actual_affected):
                plausible_root_cause = f"{main_channel} cascade (heuristic)"
                
        # 7. Construct JSON
        event = {
            "segment_id": int(segment_id),
            "channel": main_channel,
            "onset_timestamp": onset_timestamp,
            "anomaly_score": max_score,
            "severity": self.get_severity(max_score),
            "top_features": top_features,
            "related_channels": related_channels,
            "plausible_root_cause": plausible_root_cause,
            "raw_window": target_df['value'].tolist()
        }
        
        return event

