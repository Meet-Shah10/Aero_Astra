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

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)



def compute_run_length(std_series, threshold=0.001):
    """
    Computes the run length of consecutive rows where rolling_std is below a threshold.
    This identifies sustained flatlines (stuck sensors).
    """
    is_flat = std_series < threshold
    groups = (is_flat != is_flat.shift()).cumsum()
    run_lengths = is_flat.groupby(groups).cumsum()
    return run_lengths.values

def extract_rolling_features(segments_df, window_size=20, include_duration=True):
    """
    Extracts row-level features from raw segments for the production pipeline.
    """
    def _segment_features(group):
        values = group['value'].values
        padded_values = np.concatenate([np.repeat(values[0], window_size - 1), values])
        s = pd.Series(padded_values)
        r = s.rolling(window=window_size)
        stds = np.nan_to_num(r.std().values[window_size-1:], nan=0.0)
        
        runs = compute_run_length(pd.Series(stds), 0.001)
        
        # We also compute the inverted std for numerical stability
        epsilon = 1e-6
        inv_std = np.log1p(1.0 / (stds + epsilon))
        
        return np.column_stack([inv_std, runs])

    feats = []
    # Use tqdm if available, otherwise fallback
    try:
        from tqdm import tqdm
        for name, group in tqdm(segments_df.groupby('segment'), desc="Extracting features"):
            feats.append(_segment_features(group))
    except ImportError:
        for name, group in segments_df.groupby('segment'):
            feats.append(_segment_features(group))
            
    X_raw = np.vstack(feats)
    
    # Return a DataFrame so columns are named
    columns = ['log_inv_std', 'flatline_duration']
    return pd.DataFrame(X_raw, columns=columns, index=segments_df.index)

def split_data(features_df, segments_df, val_ratio=0.2, random_state=42):
    """
    Generates consistent train, val, and test splits at the segment level.
    """
    train_mask_seg = (features_df["train"] == 1).values
    val_indices = np.random.RandomState(random_state).choice(
        np.where(train_mask_seg)[0], 
        size=int(val_ratio * train_mask_seg.sum()), 
        replace=False
    )
    val_mask_seg = np.zeros_like(train_mask_seg, dtype=bool)
    val_mask_seg[val_indices] = True
    pure_train_mask_seg = train_mask_seg & ~val_mask_seg
    
    pure_train_segments = features_df.loc[pure_train_mask_seg, 'segment'].values
    val_segments = features_df.loc[val_mask_seg, 'segment'].values
    test_segments = features_df.loc[features_df["train"] == 0, 'segment'].values
    
    pure_train_mask = segments_df['segment'].isin(pure_train_segments).values
    val_mask = segments_df['segment'].isin(val_segments).values
    test_mask = segments_df['segment'].isin(test_segments).values
    
    return {
        'pure_train_mask': pure_train_mask,
        'val_mask': val_mask,
        'test_mask': test_mask
    }

def evaluate_model(y_true, scores, name="Model", threshold=None, is_val=False, precision_floor=0.5):
    """
    Evaluates a model given true labels and raw outlier scores.
    Expects HIGHER scores = MORE ANOMALOUS.
    If threshold is None, it tunes the threshold to maximize F1 (with optional precision floor).
    """
    roc_auc = roc_auc_score(y_true, scores)
    pr_auc = average_precision_score(y_true, scores)
    
    best_t = threshold
    if threshold is None:
        best_f1 = 0
        best_t = 0
        mn, mx = scores.min(), scores.max()
        # Tune threshold
        for t in np.linspace(mn, mx, 100):
            preds = (scores >= t).astype(int)
            p = precision_score(y_true, preds, zero_division=0)
            f1 = f1_score(y_true, preds, zero_division=0)
            # Only consider thresholds that meet precision floor to avoid degenerate "predict all" solutions
            if p >= precision_floor and f1 > best_f1:
                best_f1 = f1
                best_t = t
                
        if best_f1 == 0:
            log.warning(f"Could not find threshold with precision >= {precision_floor}. Falling back to simple F1 maximization.")
            for t in np.linspace(mn, mx, 100):
                preds = (scores >= t).astype(int)
                f1 = f1_score(y_true, preds, zero_division=0)
                if f1 > best_f1:
                    best_f1 = f1
                    best_t = t
                    
    preds = (scores >= best_t).astype(int)
    p = precision_score(y_true, preds, zero_division=0)
    r = recall_score(y_true, preds, zero_division=0)
    f1 = f1_score(y_true, preds, zero_division=0)
    cm = confusion_matrix(y_true, preds)
    
    log.info(f"\n============================================================")
    log.info(f"EVALUATION: {name}")
    log.info(f"============================================================")
    log.info(f"  Threshold : {best_t:.4f}")
    log.info(f"  Precision : {p:.4f}")
    log.info(f"  Recall    : {r:.4f}")
    log.info(f"  F1 Score  : {f1:.4f}")
    log.info(f"  ROC-AUC   : {roc_auc:.4f}")
    log.info(f"  PR-AUC    : {pr_auc:.4f}")
    log.info(f"\nConfusion Matrix:\n{cm}")
    
    return {
        'threshold': best_t,
        'precision': p,
        'recall': r,
        'f1': f1,
        'roc_auc': roc_auc,
        'pr_auc': pr_auc,
        'confusion_matrix': cm.tolist()
    }

