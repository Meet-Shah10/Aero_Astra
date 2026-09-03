import pandas as pd
import numpy as np
import logging
import json
from pathlib import Path
import joblib
import xgboost as xgb
from sklearn.model_selection import GroupKFold
from utils import extract_rolling_features, split_data, evaluate_model

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# Paths
ROOT = Path("/Users/meetshah1004/Desktop/Meet/Banglore_Space/Aero_Astra/backend")
DATA_DIR = ROOT / "data" / "raw" / "opssat"
MODELS_DIR = ROOT / "models"
RESULTS_DIR = ROOT / "results"

MODELS_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_DIR.mkdir(exist_ok=True, parents=True)

def main():
    log.info("=" * 60)
    log.info("SENTINEL — MODEL TRAINING (XGBOOST)")
    log.info("=" * 60)
    
    # 1. Load Data
    log.info("Loading raw telemetry data...")
    features_df = pd.read_csv(DATA_DIR / "dataset.csv")
    segments_df = pd.read_csv(DATA_DIR / "segments.csv")
    
    # Ensure chronological sort within segments
    segments_df['timestamp_dt'] = pd.to_datetime(segments_df['timestamp'])
    segments_df.sort_values(by=['segment', 'timestamp_dt'], inplace=True)
    segments_df.reset_index(drop=True, inplace=True)
    
    # 2. Feature Engineering
    log.info("Extracting rolling row-level features (duration and inverse std)...")
    feats_df = extract_rolling_features(segments_df, window_size=20)
    
    feature_cols = ['flatline_duration', 'log_inv_std']
    
    # 3. Leakage-Safe Splitting
    log.info("Applying segment-level chronological split...")
    splits = split_data(features_df, segments_df)
    train_cv_mask = splits['pure_train_mask'] | splits['val_mask']
    test_mask = splits['test_mask']
    
    y_train_cv = segments_df.loc[train_cv_mask, 'anomaly'].values
    groups_train_cv = segments_df.loc[train_cv_mask, 'segment'].values
    X_train_cv = feats_df.loc[train_cv_mask, feature_cols].values
    
    y_test = segments_df.loc[test_mask, 'anomaly'].values
    test_df = segments_df[test_mask].copy()
    X_test = feats_df.loc[test_mask, feature_cols].values
    
    log.info(f"Train/Val Pool Rows: {len(X_train_cv)} | Test Rows: {len(X_test)}")
    
    # 4. Tune Threshold via OOF Cross-Validation
    log.info("Tuning decision threshold via 5-Fold OOF Predictions to prevent leakage...")
    
    scale_pos_weight = (len(y_train_cv) - y_train_cv.sum()) / y_train_cv.sum()
    
    final_model = xgb.XGBClassifier(
        max_depth=7,
        n_estimators=200,
        learning_rate=0.01,
        scale_pos_weight=scale_pos_weight,
        eval_metric='logloss',
        random_state=42,
        n_jobs=-1
    )
    
    gkf = GroupKFold(n_splits=5)
    oof_preds = np.zeros(len(y_train_cv))
    
    for train_idx, val_idx in gkf.split(X_train_cv, y_train_cv, groups_train_cv):
        fold_model = xgb.XGBClassifier(**final_model.get_params())
        fold_model.fit(X_train_cv[train_idx], y_train_cv[train_idx])
        oof_preds[val_idx] = fold_model.predict_proba(X_train_cv[val_idx])[:, 1]
        
    cv_metrics = evaluate_model(y_train_cv, oof_preds, name="OOF Cross-Validation", is_val=True, precision_floor=0.5)
    best_threshold = cv_metrics['threshold']
    
    # 5. Train Final Production Model
    log.info("Training final production model on full Train/Val pool...")
    final_model.fit(X_train_cv, y_train_cv)
    
    # 6. Evaluate on Test Set
    log.info("Evaluating test set strictly once...")
    test_probs = final_model.predict_proba(X_test)[:, 1]
    
    test_metrics = evaluate_model(
        y_test,
        test_probs,
        name="XGBoost (Test - Row Level)",
        threshold=best_threshold,
        is_val=False
    )
    
    # Degenerate-classifier check
    pred_pos_frac = np.mean(test_probs >= best_threshold)
    base_rate = np.mean(y_test)
    log.info(f"Predicted Positive Fraction: {pred_pos_frac:.4f} (True Base Rate: {base_rate:.4f})")
    
    # Feature Importances
    importances = final_model.feature_importances_
    log.info("Feature Importances:")
    for f, imp in zip(feature_cols, importances):
        log.info(f"  {f}: {imp:.4f}")
    
    # 7. Segment-level Evaluation
    log.info("Aggregating scores for segment-level evaluation (Max Prob per Segment)...")
    
    test_df_copy = test_df.copy()
    test_df_copy['score'] = test_probs
    
    segment_scores = test_df_copy.groupby('segment')['score'].max().values
    segment_labels = test_df_copy.groupby('segment')['anomaly'].max().values
    
    seg_metrics = evaluate_model(
        segment_labels,
        segment_scores,
        name="XGBoost (Test - Segment Level)",
        threshold=best_threshold,
        is_val=False
    )
    
    # 8. Save final evaluation report and models
    log.info("Saving results and models...")
    
    # Read existing IF results to keep them for comparison
    results_path = RESULTS_DIR / "sentinel_eval.json"
    old_report = {}
    if results_path.exists():
        try:
            with open(results_path, "r") as f:
                old_report = json.load(f)
        except Exception as e:
            log.warning(f"Failed to load old results: {e}")
            
    # Extract the old IF baseline if it exists, otherwise use a placeholder
    if_baseline = old_report.get("isolation_forest_baseline") 
    if not if_baseline and "model" in old_report and "Isolation" in old_report["model"]:
        if_baseline = {
            "model": old_report.get("model"),
            "row_level_test": old_report.get("row_level_test"),
            "segment_level_test": old_report.get("segment_level_test")
        }
    
    new_report = {
        "production_model": "XGBoost (Supervised, Combined Features)",
        "features": feature_cols,
        "row_level_cv": cv_metrics,
        "row_level_test": test_metrics,
        "segment_level_test": seg_metrics,
        "isolation_forest_baseline": if_baseline
    }
    
    with open(results_path, "w") as f:
        json.dump(new_report, f, indent=4, cls=NpEncoder)
        
    joblib.dump(final_model, MODELS_DIR / "sentinel_production.pkl")
    log.info("Pipeline Complete!")
    log.info(f"Saved evaluation report to {results_path}")
    log.info(f"Saved model to models/sentinel_production.pkl")

if __name__ == "__main__":
    main()
