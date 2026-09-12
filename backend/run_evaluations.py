"""
AERO-ASTRA — Evaluation Runner
================================
Runs fresh evaluations for:
  1. XGBoost Sentinel (anomaly detection on OPSSAT test split)
  2. ATHENA RAG Pipeline (retrieval quality — all 7 FDIR queries)

Outputs (all in backend/results/):
  results/xgboost_eval.json            — row + segment level metrics + feature importances
  results/xgboost_eval_report.md       — human-readable Markdown
  results/rag_eval.json                — aggregate + per-query metrics
  results/rag_eval_report.md           — full Markdown with passage tables

Usage:
    python backend/run_evaluations.py            # run everything
    python backend/run_evaluations.py --xgb-only
    python backend/run_evaluations.py --rag-only
    python backend/run_evaluations.py --top-k 6  # change RAG retrieval K
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("eval_runner")

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent          # backend/
DATA_DIR   = ROOT / "data" / "raw" / "opssat"
MODELS_DIR = ROOT / "models"
RESULTS    = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

_TS = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):   return int(obj)
        if isinstance(obj, (np.floating,)):  return float(obj)
        if isinstance(obj, np.ndarray):      return obj.tolist()
        return super().default(obj)


# ──────────────────────────────────────────────────────────────────────────────
# 1.  XGBoost Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _run_xgboost_eval(top_k_rag: int | None = None) -> dict:
    """
    Load the trained XGBoost model and evaluate it on the held-out OPSSAT
    test split (same methodology as train.py).

    Returns a dict of all metrics (JSON-serialisable).
    """
    import joblib
    import xgboost as xgb
    from sklearn.metrics import (
        precision_score, recall_score, f1_score,
        roc_auc_score, average_precision_score,
        confusion_matrix,
    )

    # Add sentinel dir to path so utils imports work
    sys.path.insert(0, str(ROOT / "sentinel"))
    from utils import extract_rolling_features, split_data, evaluate_model  # noqa: E402

    log.info("=" * 60)
    log.info("XGBoost Sentinel Evaluation")
    log.info("=" * 60)

    # ── Load data ──────────────────────────────────────────────────────────────
    log.info("Loading OPSSAT telemetry data …")
    features_df  = pd.read_csv(DATA_DIR / "dataset.csv")
    segments_df  = pd.read_csv(DATA_DIR / "segments.csv")

    segments_df["timestamp_dt"] = pd.to_datetime(segments_df["timestamp"])
    segments_df.sort_values(by=["segment", "timestamp_dt"], inplace=True)
    segments_df.reset_index(drop=True, inplace=True)

    # ── Feature engineering ────────────────────────────────────────────────────
    log.info("Extracting rolling features …")
    feats_df     = extract_rolling_features(segments_df, window_size=20, show_progress=True)
    feature_cols = ["flatline_duration", "log_inv_std"]

    # ── Data split (same seeds as train.py) ────────────────────────────────────
    splits       = split_data(features_df, segments_df)
    test_mask    = splits["test_mask"]

    y_test   = segments_df.loc[test_mask, "anomaly"].values
    X_test   = feats_df.loc[test_mask, feature_cols].values
    test_df  = segments_df[test_mask].copy()

    log.info("Test rows: %d  |  Anomaly base-rate: %.4f", len(y_test), y_test.mean())

    # ── Load model ─────────────────────────────────────────────────────────────
    model_path = MODELS_DIR / "sentinel_production.pkl"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Trained model not found at {model_path}.\n"
            "Run: cd backend/sentinel && python train.py"
        )
    model = joblib.load(model_path)
    log.info("Model loaded: %s", model_path.name)

    # ── Inference ──────────────────────────────────────────────────────────────
    t0         = time.perf_counter()
    test_probs = model.predict_proba(X_test)[:, 1]
    infer_ms   = (time.perf_counter() - t0) * 1000
    log.info("Inference: %.1f ms for %d rows (%.3f ms/row)", infer_ms, len(y_test), infer_ms / len(y_test))

    # ── Tune threshold on OOF CV scores using same logic as train.py ──────────
    # Since we don't redo full CV here, load the saved threshold from prior run
    # if sentinel_eval.json exists; otherwise sweep on test set (informational).
    saved_eval_path = RESULTS / "sentinel_eval.json"
    best_threshold = None
    if saved_eval_path.exists():
        try:
            with open(saved_eval_path) as f:
                old = json.load(f)
            best_threshold = old.get("row_level_test", {}).get("threshold")
            if best_threshold:
                log.info("Using previously tuned threshold: %.4f", best_threshold)
        except Exception:
            pass

    # ── Row-level evaluation ───────────────────────────────────────────────────
    log.info("Computing row-level metrics …")
    row_metrics = evaluate_model(
        y_test, test_probs,
        name="XGBoost — Row-Level (Test Set)",
        threshold=best_threshold,
        is_val=False,
    )
    best_threshold = row_metrics["threshold"]  # update with actual threshold used

    # ── Segment-level evaluation ───────────────────────────────────────────────
    log.info("Computing segment-level metrics …")
    test_df_copy = test_df.copy()
    test_df_copy["score"] = test_probs

    seg_scores = test_df_copy.groupby("segment")["score"].max().values
    seg_labels = test_df_copy.groupby("segment")["anomaly"].max().values

    seg_metrics = evaluate_model(
        seg_labels, seg_scores,
        name="XGBoost — Segment-Level (Test Set)",
        threshold=best_threshold,
        is_val=False,
    )

    # ── Feature importances ────────────────────────────────────────────────────
    importances = {
        col: float(imp)
        for col, imp in zip(feature_cols, model.feature_importances_)
    }
    log.info("Feature importances: %s", importances)

    # ── Positive rate check ────────────────────────────────────────────────────
    pred_pos_frac = float(np.mean(test_probs >= best_threshold))
    base_rate     = float(y_test.mean())
    log.info("Predicted positive fraction: %.4f  (true base rate: %.4f)", pred_pos_frac, base_rate)

    report = {
        "generated_at":          _TS,
        "model":                  str(model_path.name),
        "dataset":                "OPSSAT (held-out test split)",
        "features":               feature_cols,
        "test_set_size":          int(len(y_test)),
        "test_anomaly_base_rate": base_rate,
        "inference_ms_total":     round(infer_ms, 2),
        "inference_ms_per_row":   round(infer_ms / len(y_test), 4),
        "threshold_used":         float(best_threshold),
        "predicted_positive_frac": pred_pos_frac,
        "row_level_test":         row_metrics,
        "segment_level_test":     seg_metrics,
        "feature_importances":    importances,
    }

    # ── Save JSON ──────────────────────────────────────────────────────────────
    json_path = RESULTS / "xgboost_eval.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=4, cls=_NpEncoder)
    log.info("XGBoost JSON report → %s", json_path)

    # ── Save Markdown ──────────────────────────────────────────────────────────
    _write_xgboost_markdown(report, RESULTS / "xgboost_eval_report.md")

    return report


def _write_xgboost_markdown(r: dict, path: Path) -> None:
    """Write a Markdown evaluation report for the XGBoost results."""

    def _metric_row(label: str, value, target, pass_val) -> str:
        icon = "✅" if pass_val else "❌"
        return f"| **{label}** | {value} | {target} | {icon} |"

    row  = r["row_level_test"]
    seg  = r["segment_level_test"]
    imps = r["feature_importances"]

    lines = [
        f"# SENTINEL XGBoost — Evaluation Report",
        "",
        f"> **Generated:** {r['generated_at']}  ",
        f"> **Model:** `{r['model']}`  ",
        f"> **Dataset:** {r['dataset']}  ",
        f"> **Features:** {', '.join(f'`{f}`' for f in r['features'])}  ",
        f"> **Decision threshold:** `{r['threshold_used']:.4f}`  ",
        "",
        "---",
        "",
        "## Aggregate Overview",
        "",
        f"| Property | Value |",
        f"|---|---|",
        f"| Test set rows | {r['test_set_size']:,} |",
        f"| Anomaly base-rate | {r['test_anomaly_base_rate']:.4f} ({r['test_anomaly_base_rate']*100:.1f}%) |",
        f"| Predicted positive fraction | {r['predicted_positive_frac']:.4f} |",
        f"| Inference time (total) | {r['inference_ms_total']:.1f} ms |",
        f"| Inference time (per row) | {r['inference_ms_per_row']:.4f} ms |",
        "",
        "---",
        "",
        "## Row-Level Metrics (Test Set)",
        "",
        "| Metric | Value | Target | Status |",
        "|---|---|---|---|",
        _metric_row("Precision", f"{row['precision']:.4f}", "≥ 0.70", row['precision'] >= 0.70),
        _metric_row("Recall",    f"{row['recall']:.4f}",    "≥ 0.60", row['recall']    >= 0.60),
        _metric_row("F1 Score",  f"{row['f1']:.4f}",        "≥ 0.65", row['f1']        >= 0.65),
        _metric_row("ROC-AUC",   f"{row['roc_auc']:.4f}",  "≥ 0.80", row['roc_auc']   >= 0.80),
        _metric_row("PR-AUC",    f"{row['pr_auc']:.4f}",   "≥ 0.60", row['pr_auc']    >= 0.60),
        "",
        f"**Confusion matrix (row-level):**",
        "",
        "```",
        f"              Predicted",
        f"              Neg    Pos",
        f"Actual Neg  [{row['confusion_matrix'][0][0]:>6} {row['confusion_matrix'][0][1]:>6}]",
        f"Actual Pos  [{row['confusion_matrix'][1][0]:>6} {row['confusion_matrix'][1][1]:>6}]",
        "```",
        "",
        "---",
        "",
        "## Segment-Level Metrics (Test Set)",
        "",
        "> Segment-level aggregation: max anomaly score per segment. This is the",
        "> operationally relevant metric — does the model flag the right *telemetry windows*?",
        "",
        "| Metric | Value | Target | Status |",
        "|---|---|---|---|",
        _metric_row("Precision", f"{seg['precision']:.4f}", "≥ 0.70", seg['precision'] >= 0.70),
        _metric_row("Recall",    f"{seg['recall']:.4f}",    "≥ 0.60", seg['recall']    >= 0.60),
        _metric_row("F1 Score",  f"{seg['f1']:.4f}",        "≥ 0.65", seg['f1']        >= 0.65),
        _metric_row("ROC-AUC",   f"{seg['roc_auc']:.4f}",  "≥ 0.80", seg['roc_auc']   >= 0.80),
        _metric_row("PR-AUC",    f"{seg['pr_auc']:.4f}",   "≥ 0.60", seg['pr_auc']    >= 0.60),
        "",
        f"**Confusion matrix (segment-level):**",
        "",
        "```",
        f"              Predicted",
        f"              Neg    Pos",
        f"Actual Neg  [{seg['confusion_matrix'][0][0]:>6} {seg['confusion_matrix'][0][1]:>6}]",
        f"Actual Pos  [{seg['confusion_matrix'][1][0]:>6} {seg['confusion_matrix'][1][1]:>6}]",
        "```",
        "",
        "---",
        "",
        "## Feature Importances",
        "",
        "| Feature | Importance (Gain) |",
        "|---|---|",
    ] + [f"| `{k}` | {v:.6f} |" for k, v in sorted(imps.items(), key=lambda x: -x[1])] + [
        "",
        "> The XGBoost model uses two features: `flatline_duration` (rolling run-length of",
        "> near-zero variance windows) and `log_inv_std` (log-inverse rolling standard deviation).",
        "> Both detect *flatline / stuck sensor* failures. The model is not designed to detect",
        "> smooth drift faults; those are handled by Engine B (physics thresholds) in production.",
        "",
        "---",
        "",
        f"*Report generated by `backend/run_evaluations.py` — {_TS}*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("XGBoost Markdown report → %s", path)
    print(f"\n📄 XGBoost Markdown report → {path}")


# ──────────────────────────────────────────────────────────────────────────────
# 2.  RAG Pipeline Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _run_rag_eval(top_k: int = 4) -> dict:
    """
    Run the ATHENA RAG evaluation suite using the built-in evaluate.py framework.
    Returns the aggregate metrics dict.
    """
    import dataclasses

    # Ensure repo root (parent of backend/) is on sys.path so `backend.*` resolves
    # regardless of where the script is invoked from.
    _repo_root = str(ROOT.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    from backend.athena.rag.pipeline import AthenaRAGPipeline, reset_pipeline_singleton
    from backend.athena.rag.evaluate import evaluate, generate_markdown_report, EXTENDED_QUERIES

    log.info("=" * 60)
    log.info("ATHENA RAG Pipeline Evaluation")
    log.info("=" * 60)

    reset_pipeline_singleton()
    rag = AthenaRAGPipeline(top_k=top_k)

    if not rag.is_ready():
        raise RuntimeError(
            "RAG vectorstore is not ready. Run:\n"
            "  python -m backend.athena.rag.seed --force-rebuild"
        )

    log.info(
        "Vectorstore ready: collection=%s | docs=%d | top_k=%d",
        rag._collection_name, rag._collection.count(), top_k,
    )

    report = evaluate(
        rag,
        queries=EXTENDED_QUERIES,
        top_k=top_k,
        suite_name="Full FDIR Evaluation Suite",
    )

    # ── Print terminal summary ─────────────────────────────────────────────────
    print("\n" + report.summary())

    # ── Serialise to JSON ──────────────────────────────────────────────────────
    def _qr_to_dict(qr):
        d = dataclasses.asdict(qr)
        d.pop("retrieved_passages", None)   # large; omit from JSON
        return d

    agg = {
        "generated_at":   _TS,
        "top_k":          report.top_k,
        "num_queries":    report.num_queries,
        "hit_rate":       round(report.hit_rate, 4),
        "mrr":            round(report.mrr, 4),
        "precision_at_k": round(report.precision_at_k, 4),
        "recall_at_k":    round(report.recall_at_k, 4),
        "avg_relevance":  round(report.avg_relevance, 4),
        "avg_latency_ms": round(report.avg_latency_ms, 2),
        "per_query":      [_qr_to_dict(qr) for qr in report.results],
    }

    json_path = RESULTS / "rag_eval.json"
    with open(json_path, "w") as f:
        json.dump(agg, f, indent=4)
    log.info("RAG JSON report → %s", json_path)

    # ── Save Markdown (uses existing generate_markdown_report) ─────────────────
    md_path = RESULTS / "rag_eval_report.md"
    generate_markdown_report(report, md_path)

    return agg


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fresh XGBoost and RAG evaluations — save reports to backend/results/",
    )
    parser.add_argument("--xgb-only", action="store_true", help="Run only XGBoost evaluation")
    parser.add_argument("--rag-only", action="store_true", help="Run only RAG evaluation")
    parser.add_argument("--top-k",  type=int, default=4, help="RAG retrieval K (default: 4)")
    args = parser.parse_args()

    run_xgb = not args.rag_only
    run_rag = not args.xgb_only

    results: dict[str, dict] = {}

    if run_xgb:
        try:
            results["xgboost"] = _run_xgboost_eval()
            log.info("✓ XGBoost evaluation complete.")
        except Exception as exc:
            log.error("XGBoost evaluation FAILED: %s", exc, exc_info=True)
            results["xgboost"] = {"error": str(exc)}

    if run_rag:
        try:
            results["rag"] = _run_rag_eval(top_k=args.top_k)
            log.info("✓ RAG evaluation complete.")
        except Exception as exc:
            log.error("RAG evaluation FAILED: %s", exc, exc_info=True)
            results["rag"] = {"error": str(exc)}

    # ── Combined summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  EVALUATION SUMMARY")
    print("=" * 60)

    if "xgboost" in results:
        r = results["xgboost"]
        if "error" in r:
            print(f"  XGBoost  : ❌ FAILED — {r['error']}")
        else:
            row = r["row_level_test"]
            seg = r["segment_level_test"]
            print(f"  XGBoost  : ✅")
            print(f"    Row-level   — P={row['precision']:.3f}  R={row['recall']:.3f}  F1={row['f1']:.3f}  AUC={row['roc_auc']:.3f}")
            print(f"    Seg-level   — P={seg['precision']:.3f}  R={seg['recall']:.3f}  F1={seg['f1']:.3f}  AUC={seg['roc_auc']:.3f}")

    if "rag" in results:
        r = results["rag"]
        if "error" in r:
            print(f"  RAG      : ❌ FAILED — {r['error']}")
        else:
            print(f"  RAG      : ✅")
            print(f"    Hit Rate @{r['top_k']} : {r['hit_rate']:.1%}")
            print(f"    MRR @{r['top_k']}      : {r['mrr']:.3f}")
            print(f"    Precision @{r['top_k']} : {r['precision_at_k']:.3f}")
            print(f"    Recall @{r['top_k']}   : {r['recall_at_k']:.3f}")
            print(f"    Avg Similarity : {r['avg_relevance']:.3f}")
            print(f"    Avg Latency    : {r['avg_latency_ms']:.1f} ms / query")

    print("=" * 60)
    print(f"\nAll reports saved to: {RESULTS}/")
    for name in ["xgboost_eval.json", "xgboost_eval_report.md", "rag_eval.json", "rag_eval_report.md"]:
        p = RESULTS / name
        if p.exists():
            print(f"  {'✅' if p.stat().st_size > 10 else '❌'} {p.name}")


if __name__ == "__main__":
    main()
