# EPS/TCS Thermal Power Anomaly Detector (SENTINEL)

**IMPORTANT WARNINGS & CAVEATS**

### 1. Semi-Supervised, Residual-Based Model
Unlike the ADCS SENTINEL pipeline (which was supervised and cross-validated against ground-truth labels), this model is entirely semi-supervised. 
- It relies on a forecaster + residual-threshold approach. 
- It predicts the expected power draw of a thermal heater line based on contextual features (solar flux, orientation, etc.) and flags an anomaly if the actual power draw deviates significantly from the prediction.

### 2. Confidence Scores are Uncalibrated
Confidence scores emitted by this model are based on the magnitude of the residual (how far actual power deviated from predicted). **These scores are NOT calibrated probabilities** and are not directly comparable to the XGBoost probability outputs of the ADCS pipeline without further calibration.

### 3. No Ground Truth Validation
Because the original Mars Express Thermal Power dataset does not contain anomaly labels, this model has **NOT been cross-validated against real anomaly ground truth**. The thresholds were tuned qualitatively by inspecting the top 1-2% of residuals per channel to confirm physical plausibility, but false positive rates remain unknown.

### 4. Subsystem Classification Mapping
All 33 target columns in this dataset (`NPWD*`) correspond to thermal heater lines.
- **Rule:** Any anomaly triggered on an `NPWD*` channel is hard-mapped to the **"TCS" (Thermal Control Subsystem)** in the `AnomalyEvent` output.
- While these heaters draw electrical power (EPS), their physical actuation purpose is thermal control. If true EPS context features (e.g., bus voltage, battery SoC) are later promoted to targets, they will map to "EPS". Until then, all outputs from this specific model resolve to TCS.
