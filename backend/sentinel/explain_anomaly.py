"""
SENTINEL — Explanatory Anomaly Module (LSTM)
Agent 1 of AERO-ASTRA

This module extracts the LSTM forecaster from the active SENTINEL pipeline and repurposes it 
strictly as an explanatory/diagnostic tool. When a sustained flatline fault is flagged by the 
production model (Isolation Forest trained on flatline duration), this module generates a 
predicted-vs-actual trace for that segment. Because flatline anomalies are highly predictable, 
the LSTM residual collapses, visually confirming to operators that a stuck-sensor fault has occurred.
"""

import os
import sys
import logging
import warnings
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from tqdm import tqdm
from sklearn.preprocessing import RobustScaler, MinMaxScaler

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Paths & Setup
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw" / "opssat"
MODELS_DIR = ROOT / "models"
RESULTS_DIR = ROOT / "results"

for d in [MODELS_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("EXPLAIN_ANOMALY")

# ─────────────────────────────────────────────────────────────────────────────
# LSTM Architecture & Utilities
# ─────────────────────────────────────────────────────────────────────────────
class LSTMForecaster(nn.Module):
    def __init__(self, input_dim=1, hidden_dim=64, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out

class TelemetryDataset(Dataset):
    def __init__(self, sequences, targets):
        self.sequences = sequences
        self.targets = targets

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        return self.sequences[idx], self.targets[idx]

def extract_padded_sequences(values, seq_len=10):
    if len(values) == 0:
        return [], []
        
    padded_values = np.concatenate([np.repeat(values[0], seq_len), values])
    seqs, targets = [], []
    
    for i in range(len(values)):
        seqs.append(padded_values[i : i+seq_len])
        targets.append(padded_values[i+seq_len])
        
    return seqs, targets

def load_and_preprocess_data():
    dataset_path = DATA_DIR / "dataset.csv"
    segments_path = DATA_DIR / "segments.csv"

    if not dataset_path.exists() or not segments_path.exists():
        log.error(f"Data not found in {DATA_DIR}")
        sys.exit(1)

    features_df = pd.read_csv(dataset_path)
    segments_df = pd.read_csv(segments_path)
    
    segments_df['timestamp_dt'] = pd.to_datetime(segments_df['timestamp'])
    segments_df.sort_values(by=['segment', 'timestamp_dt'], inplace=True)
    segments_df.reset_index(drop=True, inplace=True)
    
    return features_df, segments_df

def build_lstm_loaders(features_df, segments_df, pure_train_mask, val_mask, seq_len=10):
    normal_train_segments = features_df.loc[pure_train_mask & (features_df['anomaly'] == 0), 'segment'].values
    normal_val_segments = features_df.loc[val_mask & (features_df['anomaly'] == 0), 'segment'].values
    
    scaler = MinMaxScaler()
    train_seg_idx = segments_df['segment'].isin(features_df.loc[pure_train_mask, 'segment'].values)
    scaler.fit(segments_df.loc[train_seg_idx, ['value']])
    segments_df['value_scaled'] = scaler.transform(segments_df[['value']])
    
    def _create_tensors(seg_list):
        X_seq, y_seq = [], []
        for seg_id in tqdm(seg_list, desc="Extracting Sequences", leave=False):
            seg_data = segments_df[segments_df['segment'] == seg_id]['value_scaled'].values
            seqs, tgts = extract_padded_sequences(seg_data, seq_len)
            X_seq.extend(seqs)
            y_seq.extend(tgts)
        if not X_seq: return None
        return torch.tensor(np.array(X_seq, dtype=np.float32)[..., np.newaxis]), \
               torch.tensor(np.array(y_seq, dtype=np.float32)[..., np.newaxis])

    log.info("Building Train Loader...")
    t_tensors = _create_tensors(normal_train_segments)
    train_loader = DataLoader(TelemetryDataset(t_tensors[0], t_tensors[1]), batch_size=512, shuffle=True) if t_tensors else None
    
    log.info("Building Validation Loader...")
    v_tensors = _create_tensors(normal_val_segments)
    val_loader = DataLoader(TelemetryDataset(v_tensors[0], v_tensors[1]), batch_size=512, shuffle=False) if v_tensors else None
    
    return train_loader, val_loader, scaler

def train_lstm(train_loader, val_loader, epochs=50, patience=5):
    if not train_loader or not val_loader:
        log.error("Loaders are empty.")
        return None
        
    model = LSTMForecaster(input_dim=1, hidden_dim=64, num_layers=2, dropout=0.2)
    device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
    model = model.to(device)
    
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    
    best_val_loss = float('inf')
    patience_counter = 0
    best_model_state = None
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            out = model(batch_x)
            loss = criterion(out, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                out = model(batch_x)
                loss = criterion(out, batch_y)
                val_loss += loss.item()
                
        t_l = train_loss / len(train_loader)
        v_l = val_loss / len(val_loader)
        
        if v_l < best_val_loss:
            best_val_loss = v_l
            best_model_state = model.state_dict().copy()
            patience_counter = 0
        else:
            patience_counter += 1
            
        log.info(f"  Epoch {epoch+1:02d}/{epochs} | Train Loss: {t_l:.6f} | Val Loss: {v_l:.6f}")
        if patience_counter >= patience:
            log.info(f"Early stopping triggered at epoch {epoch+1}")
            break
            
    model.load_state_dict(best_model_state)
    model.eval()
    model = model.cpu()
    torch.save(model.state_dict(), MODELS_DIR / "sentinel_lstm.pt")
    return model

def explain_segment(segment_id, model, segments_df, scaler, seq_len=10):
    """
    Concrete explanatory consumer: given a flagged segment, run the LSTM forecaster 
    and plot the predicted vs actual values to visually explain the anomaly.
    """
    log.info(f"Generating anomaly explanation trace for segment {segment_id}")
    
    group = segments_df[segments_df['segment'] == segment_id]
    if group.empty:
        log.error(f"Segment {segment_id} not found in data.")
        return
        
    device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
    model = model.to(device)
    model.eval()
    
    seg_data = group['value'].values.reshape(-1, 1)
    seg_data_scaled = scaler.transform(seg_data).flatten()
    
    seqs, _ = extract_padded_sequences(seg_data_scaled, seq_len)
    
    with torch.no_grad():
        x_tensor = torch.tensor(np.array(seqs, dtype=np.float32)).unsqueeze(-1).to(device)
        preds_scaled = model(x_tensor).cpu().numpy().flatten()
        
    preds = scaler.inverse_transform(preds_scaled.reshape(-1, 1)).flatten()
    actuals = seg_data.flatten()
    
    errors = np.abs(actuals - preds)
    
    # Plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    time_axis = np.arange(len(actuals))
    
    ax1.plot(time_axis, actuals, label='Actual Telemetry', color='black', alpha=0.7)
    ax1.plot(time_axis, preds, label='LSTM Predicted', color='red', linestyle='--')
    ax1.set_title(f"Predicted vs Actual Trace for Segment: {segment_id}")
    ax1.set_ylabel("Value")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    ax2.fill_between(time_axis, 0, errors, color='red', alpha=0.3, label='Absolute Error (Residual)')
    ax2.set_title("Prediction Error (Residual)")
    ax2.set_ylabel("Error")
    ax2.set_xlabel("Timestep")
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    save_path = RESULTS_DIR / f"explanation_trace_{segment_id}.png"
    plt.savefig(save_path)
    plt.close()
    
    log.info(f"Explanation trace saved to {save_path}")

def demo_explanation():
    features_df, segments_df = load_and_preprocess_data()
    
    # Prepare train/val splits for scaler
    train_mask = (features_df["train"] == 1).values
    np.random.seed(42)
    val_indices = np.random.choice(np.where(train_mask)[0], size=int(0.2 * train_mask.sum()), replace=False)
    val_mask = np.zeros_like(train_mask, dtype=bool)
    val_mask[val_indices] = True
    pure_train_mask = train_mask & ~val_mask
    
    model_path = MODELS_DIR / "sentinel_lstm.pt"
    
    train_loader, val_loader, scaler = build_lstm_loaders(features_df, segments_df, pure_train_mask, val_mask)
    
    if model_path.exists():
        log.info(f"Loading existing LSTM model from {model_path}")
        model = LSTMForecaster(input_dim=1, hidden_dim=64, num_layers=2, dropout=0.2)
        model.load_state_dict(torch.load(model_path))
    else:
        log.info("No saved model found, training a quick explanatory model...")
        model = train_lstm(train_loader, val_loader, epochs=5, patience=2)
        
    # Find an anomalous segment in the test set to explain
    test_anomalous_segments = features_df[(features_df['train'] == 0) & (features_df['anomaly'] == 1)]['segment'].values
    if len(test_anomalous_segments) > 0:
        sample_segment = test_anomalous_segments[0]
        explain_segment(sample_segment, model, segments_df, scaler)

if __name__ == "__main__":
    demo_explanation()
