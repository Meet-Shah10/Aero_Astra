import sys
import json
import random
from pathlib import Path

# Append backend to path to import sentinel correctly
ROOT = Path("/Users/meetshah1004/Desktop/Meet/Banglore_Space/Aero_Astra/backend")
sys.path.append(str(ROOT))

from sentinel.root_cause import RootCauseAnalyzer

def main():
    print("="*60)
    print("SENTINEL END-TO-END TEST")
    print("="*60)
    
    analyzer = RootCauseAnalyzer()
    
    # 1. Find a flagged segment from the test set
    test_anomalies = analyzer.segments_df[
        (analyzer.segments_df['train'] == 0) & 
        (analyzer.segments_df['anomaly'] == 1)
    ]['segment'].unique()
    
    if len(test_anomalies) == 0:
        print("No anomalous test segments found.")
        return
        
    # Pick a random segment to test
    seg_id = random.choice(test_anomalies)
    target_df = analyzer.segments_df[analyzer.segments_df['segment'] == seg_id]
    
    # --- DISPLAY INPUT ---
    print(f"\n[1] RAW INPUT TELEMETRY (Segment ID: {seg_id})")
    print("-" * 60)
    print(f"Channel: {target_df['channel'].iloc[0]}")
    print(f"Time Range: {target_df['timestamp'].min()} to {target_df['timestamp'].max()}")
    print(f"Total Data Points: {len(target_df)}")
    
    print("\nPreview of raw telemetry values:")
    values = target_df['value'].tolist()
    # Print first 5 and last 5 values
    for i in range(min(5, len(values))):
        print(f"  t[{i}]: {values[i]:.6f}")
    if len(values) > 10:
        print("  ...")
    for i in range(max(len(values)-5, 5), len(values)):
        print(f"  t[{i}]: {values[i]:.6f}")
        
    # --- RUN SENTINEL ---
    print(f"\n[2] RUNNING SENTINEL PIPELINE...")
    print("-" * 60)
    event = analyzer.analyze_segment(seg_id)
    
    # --- DISPLAY OUTPUT ---
    print(f"\n[3] SENTINEL JSON OUTPUT")
    print("-" * 60)
    
    if event:
        # Simplify the raw_window array for clean terminal printing
        event_print = event.copy()
        event_print['raw_window'] = f"[{len(event['raw_window'])} raw telemetry points omitted for brevity]"
        print(json.dumps(event_print, indent=2))
    else:
        print("Pipeline failed to generate an event.")
        
    print("\n" + "="*60)

if __name__ == "__main__":
    main()
