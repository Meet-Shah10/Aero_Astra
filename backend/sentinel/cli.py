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

from .adcs import train_adcs
from .lstm import demo_explanation
from .eps_tcs import train_eps_tcs, eval_eps_tcs
from .root_cause import RootCauseAnalyzer

def main():
    parser = argparse.ArgumentParser(description="SENTINEL Unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("train-adcs", help="Train ADCS model")
    subparsers.add_parser("train-eps", help="Train EPS/TCS model")
    subparsers.add_parser("eval-eps", help="Evaluate EPS/TCS thresholds")
    subparsers.add_parser("demo-explain", help="Demo LSTM explanation trace")
    subparsers.add_parser("hybrid-eval", help="Evaluate Hybrid Three-Engine Detector")
    
    args = parser.parse_args()
    
    if args.command == "train-adcs":
        train_adcs()
    elif args.command == "train-eps":
        train_eps_tcs()
    elif args.command == "eval-eps":
        eval_eps_tcs()
    elif args.command == "demo-explain":
        demo_explanation()
    elif args.command == "hybrid-eval":
        from .evaluate_three_engine import main as eval_hybrid_main
        eval_hybrid_main()
    else:
        parser.print_help()
