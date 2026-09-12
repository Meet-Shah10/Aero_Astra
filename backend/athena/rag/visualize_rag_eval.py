import os
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True, parents=True)

def generate_rag_visualization():
    # Data from EVAL_REPORT.md
    faults = [
        "TCS Thermal", 
        "TT&C Signal", 
        "Propulsion", 
        "EPS Battery", 
        "ADCS Wheel", 
        "EPS Cascade", 
        "Gen. FDIR"
    ]
    
    precision = [1.00, 0.75, 0.50, 0.50, 0.50, 0.75, 0.50]
    recall = [1.00, 1.00, 0.67, 0.50, 0.67, 1.00, 0.67]
    latency = [1905, 1006, 532, 1036, 1103, 1243, 1037]
    
    x = np.arange(len(faults))
    width = 0.35

    # 1. Precision and Recall Bar Chart
    fig, ax1 = plt.subplots(figsize=(10, 6))
    
    rects1 = ax1.bar(x - width/2, precision, width, label='Precision@4', color='skyblue')
    rects2 = ax1.bar(x + width/2, recall, width, label='Recall@4', color='lightcoral')

    ax1.set_ylabel('Score (0.0 to 1.0)')
    ax1.set_title('ATHENA RAG Pipeline Retrieval Metrics by Fault Scenario')
    ax1.set_xticks(x)
    ax1.set_xticklabels(faults, rotation=45, ha='right')
    ax1.set_ylim(0, 1.1)
    ax1.legend(loc='upper right')
    
    # Add values on top of bars
    ax1.bar_label(rects1, padding=3, fmt='%.2f')
    ax1.bar_label(rects2, padding=3, fmt='%.2f')
    
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "rag_precision_recall.png")
    plt.close()
    
    # 2. Latency Chart
    fig, ax2 = plt.subplots(figsize=(10, 6))
    
    colors = ['orange' if l > 1000 else 'mediumseagreen' for l in latency]
    rects3 = ax2.bar(faults, latency, color=colors)
    
    ax2.axhline(y=1000, color='r', linestyle='--', label='Target Latency (1000ms)')
    ax2.set_ylabel('Latency (ms)')
    ax2.set_title('ATHENA RAG Retrieval Latency by Fault Scenario')
    ax2.set_xticklabels(faults, rotation=45, ha='right')
    ax2.legend()
    
    ax2.bar_label(rects3, padding=3, fmt='%d ms')
    
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "rag_latency.png")
    plt.close()
    
    print("RAG visualizations generated in backend/results/")

if __name__ == "__main__":
    generate_rag_visualization()
