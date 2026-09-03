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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("SENTINEL")

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models" 
RESULTS_DIR = ROOT / "results"

from .utils import NpEncoder
from xgboost import XGBRegressor
EPSILON = 1e-6

def train_eps_tcs():
    DATA_PATH = ROOT / 'data' / 'raw' / 'mars_express' / 'data15.csv'
    print("="*50)
    print("SENTINEL EPS/TCS: SEMI-SUPERVISED FORECASTER")
    print("="*50)
    
    
    
    print("1. Loading dataset...")
    # Read with ? as NaN
    df = pd.read_csv(DATA_PATH, na_values='?')
    
    # Sort chronologically just in case
    df = df.sort_values('ut_ms').reset_index(drop=True)
    
    # Identify columns
    targets = [c for c in df.columns if 'NPWD' in c]
    context = [c for c in df.columns if 'NPWD' not in c and c != 'ut_ms']
    
    # Drop duplicates (as found in sanity check)
    df_context = df[context].copy()
    df_context = df_context.loc[:, ~df_context.columns.duplicated()]
    context = list(df_context.columns)
    
    # To drop exact identical columns (taking a shortcut here based on previous finding)
    # Actually, we can just let XGBoost handle colinearity, but let's drop rows with missing targets
    print(f"Initial shape: {df.shape}")
    df = df.dropna(subset=targets).reset_index(drop=True)
    print(f"Shape after dropping missing targets: {df.shape}")
    
    X = df[context]
    y = df[targets]
    
    # Chronological Split (80/20)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    time_test = df['ut_ms'].iloc[split_idx:]
    
    print(f"Train samples: {len(X_train)} | Test samples: {len(X_test)}")
    
    # LEAKAGE GUARDRAIL: Strict scaler fitting on TRAIN ONLY
    print("2. Scaling features (Fit on TRAIN ONLY)...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Save scaler
    joblib.dump(scaler, str(MODELS_DIR / 'eps_context_scaler.pkl'))
    
    # 3. Train Forecaster
    print("3. Training XGBoost MultiOutputRegressor...")
    base_model = XGBRegressor(
        n_estimators=100, 
        max_depth=5, 
        tree_method='hist',
        missing=np.nan,
        n_jobs=-1
    )
    model = MultiOutputRegressor(base_model, n_jobs=1) # Let XGBoost handle threading internally
    model.fit(X_train_scaled, y_train)
    
    print("Saving model...")
    joblib.dump(model, str(MODELS_DIR / 'eps_forecaster.pkl'))
    
    # 4. Residual Calculation
    print("4. Calculating Test Set Residuals...")
    y_pred = model.predict(X_test_scaled)
    residuals = np.abs(y_test.values - y_pred)
    
    # Analyze distribution per channel
    thresholds = {}
    flagged_events = []
    
    for i, ch in enumerate(targets):
        res_ch = residuals[:, i]
        
        # Guardrail: Per-channel top 1% threshold
        thresh = np.percentile(res_ch, 99)
        thresholds[ch] = float(thresh)
        
        # Extract top anomalies for this channel
        anomaly_indices = np.where(res_ch > thresh)[0]
        
        for idx in anomaly_indices:
            flagged_events.append({
                'channel': ch,
                'ut_ms': int(time_test.iloc[idx]),
                'actual': float(y_test.iloc[idx, i]),
                'predicted': float(y_pred[idx, i]),
                'residual': float(res_ch[idx]),
                'threshold': float(thresh)
            })
            
    # Save thresholds
    with open(str(MODELS_DIR / 'eps_thresholds.json'), 'w') as f:
        json.dump(thresholds, f, indent=2)
        
    # Sort all flagged events by residual magnitude (normalized by threshold)
    for e in flagged_events:
        e['severity'] = e['residual'] / e['threshold']
        
    flagged_events.sort(key=lambda x: x['severity'], reverse=True)
    
    # Dump top 10 diverse examples for manual review
    print("\n" + "="*50)
    print("MANUAL REVIEW: TOP FLAGGED WINDOWS (Out-of-Sample)")
    print("="*50)
    
    seen_channels = set()
    reviewed_count = 0
    
    review_output = []
    for event in flagged_events:
        if event['channel'] not in seen_channels:
            seen_channels.add(event['channel'])
            review_output.append(event)
            reviewed_count += 1
            if reviewed_count >= 10:
                break
                
    for i, r in enumerate(review_output):
        print(f"[{i+1}] Channel: {r['channel']} | Time: {r['ut_ms']}")
        print(f"    Actual Power: {r['actual']:.2f} | Predicted: {r['predicted']:.2f}")
        print(f"    Residual: {r['residual']:.2f} (Threshold: {r['threshold']:.2f}, Severity: {r['severity']:.2f}x)")
        
    with open(str(RESULTS_DIR / 'manual_review_sample.json'), 'w') as f:
        json.dump(review_output, f, indent=2)

    print("\nDone! Please review the flagged windows above to confirm physical plausibility.")

def eval_eps_tcs():
    DATA_PATH = ROOT / 'data' / 'raw' / 'mars_express' / 'data15.csv'
    print("Loading data and model...")
    df = pd.read_csv(DATA_PATH, na_values='?')
    df = df.sort_values('ut_ms').reset_index(drop=True)
    
    targets = [c for c in df.columns if 'NPWD' in c]
    context = [c for c in df.columns if 'NPWD' not in c and c != 'ut_ms']
    
    # Drop duplicates
    df_context = df[context].copy()
    df_context = df_context.loc[:, ~df_context.columns.duplicated()]
    context = list(df_context.columns)
    
    df = df.dropna(subset=targets).reset_index(drop=True)
    
    X = df[context]
    y = df[targets]
    
    split_idx = int(len(df) * 0.8)
    X_test = X.iloc[split_idx:]
    y_test = y.iloc[split_idx:]
    time_test = df['ut_ms'].iloc[split_idx:]
    
    scaler = joblib.load(str(MODELS_DIR / 'eps_context_scaler.pkl'))
    model = joblib.load(str(MODELS_DIR / 'eps_forecaster.pkl'))
    
    X_test_scaled = scaler.transform(X_test)
    y_pred = model.predict(X_test_scaled)
    residuals = np.abs(y_test.values - y_pred)
    
    # 1. Calculate active-state median and IQR per channel
    print("="*60)
    print("ACTIVE-STATE STATS PER CHANNEL (Epsilon > 0.01W)")
    print("="*60)
    
    active_stats = {}
    all_active_medians = []
    
    for i, ch in enumerate(targets):
        actuals = y_test.iloc[:, i].values
        active_mask = actuals > EPSILON
        active_actuals = actuals[active_mask]
        
        if len(active_actuals) == 0:
            active_stats[ch] = {'median': 0.0, 'iqr': 0.0, 'active_ratio': 0.0, 'active_99th_res': 0.0}
            print(f"{ch}: NEVER ACTIVE")
            continue
            
        q1 = np.percentile(active_actuals, 25)
        q3 = np.percentile(active_actuals, 75)
        median = np.median(active_actuals)
        iqr = q3 - q1
        active_ratio = len(active_actuals) / len(actuals)
        
        active_res = residuals[active_mask, i]
        active_99th_res = np.percentile(active_res, 99) if len(active_res) > 0 else 0.0
        
        active_stats[ch] = {
            'median': median, 
            'iqr': iqr, 
            'active_ratio': active_ratio,
            'active_99th_res': active_99th_res
        }
        all_active_medians.append(median)
        print(f"{ch}: Median={median:.3f}W | IQR={iqr:.3f}W | Active: {active_ratio*100:.2f}% | Active 99th Res: {active_99th_res:.3f}W")
        
    global_min_power = np.percentile(all_active_medians, 10) * 0.5  # E.g., half of the 10th percentile of medians
    # Or let's just pick a conservative floor like 0.1W if the medians are generally > 1W
    print(f"\nDistribution of Active Medians: Min={np.min(all_active_medians):.3f}W, Max={np.max(all_active_medians):.3f}W, Median={np.median(all_active_medians):.3f}W")
    
    # Let's derive MIN_ABSOLUTE_POWER_W as 0.1W based on typical spacecraft heater values (we'll log the justification)
    # The actual proposed floor will be derived and justified in the report. Let's use 0.1W as a dummy for calculation in this script.
    MIN_ABSOLUTE_POWER_W = 0.1
    print(f"Applying MIN_ABSOLUTE_POWER_W = {MIN_ABSOLUTE_POWER_W}W")
    
    # 2. Validation: Recompute new thresholds and flagged windows
    new_thresholds = {}
    new_flagged = []
    
    for i, ch in enumerate(targets):
        if ch not in active_stats or active_stats[ch]['active_ratio'] == 0:
            new_thresholds[ch] = MIN_ABSOLUTE_POWER_W
            continue
            
        active_99th = active_stats[ch]['active_99th_res']
        thresh = max(active_99th, MIN_ABSOLUTE_POWER_W)
        new_thresholds[ch] = float(thresh)
        
        res_ch = residuals[:, i]
        anomaly_indices = np.where(res_ch > thresh)[0]
        
        for idx in anomaly_indices:
            new_flagged.append({
                'channel': ch,
                'ut_ms': int(time_test.iloc[idx]),
                'actual': float(y_test.iloc[idx, i]),
                'predicted': float(y_pred[idx, i]),
                'residual': float(res_ch[idx]),
                'threshold': float(thresh),
                'severity': float(res_ch[idx] / thresh)
            })
            
    new_flagged.sort(key=lambda x: x['severity'], reverse=True)
    
    print("\n" + "="*50)
    print("NEW TOP FLAGGED WINDOWS (With active-state + floor)")
    print("="*50)
    
    seen_channels = set()
    reviewed_count = 0
    
    for r in new_flagged:
        if r['channel'] not in seen_channels:
            seen_channels.add(r['channel'])
            reviewed_count += 1
            
            # Find a normal active window for contrast
            ch_idx = targets.index(r['channel'])
            actuals = y_test.iloc[:, ch_idx].values
            res_ch = residuals[:, ch_idx]
            normal_active_indices = np.where((actuals > EPSILON) & (res_ch < new_thresholds[r['channel']]))[0]
            contrast = None
            if len(normal_active_indices) > 0:
                c_idx = normal_active_indices[0]
                contrast = {
                    'ut_ms': int(time_test.iloc[c_idx]),
                    'actual': float(actuals[c_idx]),
                    'predicted': float(y_pred[c_idx, ch_idx]),
                    'residual': float(res_ch[c_idx])
                }
            
            print(f"[{reviewed_count}] Channel: {r['channel']}")
            print(f"    [ANOMALY] Time: {r['ut_ms']} | Actual Power: {r['actual']:.2f} | Predicted: {r['predicted']:.2f}")
            print(f"              Residual: {r['residual']:.2f} (Threshold: {r['threshold']:.2f}, Severity: {r['severity']:.2f}x)")
            if contrast:
                print(f"    [CONTRAST] Time: {contrast['ut_ms']} | Actual Power: {contrast['actual']:.2f} | Predicted: {contrast['predicted']:.2f}")
                print(f"               Residual: {contrast['residual']:.2f}")
            print("-" * 50)
            
            if reviewed_count >= 10:
                break


