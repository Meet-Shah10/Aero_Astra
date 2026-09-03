# SENTINEL: Anomaly Detection Engine

## Overview
**SENTINEL** is the first line of defense in the AERO-ASTRA pipeline. Designed to monitor incoming satellite telemetry continuously, its primary role is to detect hardware faults, sensor anomalies, and physical degradation in real-time, subsequently triggering the downstream SHERLOCK (diagnosis) and GUARDIAN (safing) agents.

Instead of relying on a single monolithic model, SENTINEL utilizes a **unified multi-engine architecture**. This hybrid approach applies targeted physical and statistical rules to different classes of anomalies, ensuring extremely high precision while minimizing False Positives (FPs).

---

## The Anomaly Signature (Physical Narrative)
In AERO-ASTRA telemetry (specifically the real ESA OPSSAT-AD dataset), quiet periods are not inherently anomalous. Approximately 38% of normal telemetry consists of low-variance, idle periods (e.g., during eclipses or safe mode). Models that blindly flag low variance or unpredictable sequences will generate overwhelming false alarms. 

The true physical signature of an anomaly in this dataset is a **persistent stuck-sensor flatline** or a **non-physical impulsive spike**.

---

## Engine A: XGBoost + Persistence
**Target:** Slow-onset hardware degradation, stuck sensors, and sustained telemetry flatlines.

### How It Works:
1. **Rolling Feature Extraction:** Over a backward-looking 20-step window, Engine A extracts highly discriminative physical features:
   - `flatline_duration` (71.58% Feature Importance): The run-length of consecutive rows where local variance drops to near zero.
   - `log_inv_std` (28.42% Feature Importance): A mathematical calculation `np.log1p(1.0 / (std + 1e-6))` that quantifies the absolute lack of volatility.
2. **XGBoost Inference:** A supervised Gradient-Boosted Tree (trained on OPSSAT-AD data) scores the likelihood of a stuck-sensor fault based on these features.
3. **Persistence Filter:** To eliminate transient operational noise (such as a sensor briefly pausing during a normal state transition), the XGBoost output is wrapped in a `SentinelPersistenceFilter`. Engine A will only raise a critical alarm if the anomaly probability remains above the threshold for **35 consecutive seconds**. 

---

## Engine B: Physics Spike & Triad Isolation
**Target:** Impulsive momentum anomalies (e.g., sudden hardware strikes, instantaneous sensor bit-flips) specifically affecting 3D rigid-body sensors like the Magnetometer triad (`CADC0872`, `CADC0873`, `CADC0874`).

*(Note: Engine B completely replaces legacy statistical drift models like CUSUM, which struggled with natural orbital heteroskedasticity and caused high False Positive rates).*

### How It Works:
Engine B utilizes deterministic, physics-constrained logic rather than machine learning:
1. **Impulse Reversal (Inertia Violation):** Evaluates the rate of change coming into a timestep (`dx_in`) and leaving it (`dx_out`). It flags an anomaly if there is a massive jump (`dx_in > 4 * MAD`) immediately followed by an opposite reversal (`dx_in * dx_out < 0`). This strictly identifies inertia violations (a physical object cannot instantly reverse momentum without external force).
2. **Single-Channel Isolation:** Enforces 3D rigid-body constraints. If the satellite executes a valid maneuver, all three axes of the triad will register a change. Engine B will *only* flag an anomaly if **exactly 1 out of the 3 axes** exhibits the spike, decoupling valid spacecraft maneuvers from isolated hardware failures.

---

## Engine C: Correlation / Fisher-Z (Dormant)
**Target:** Cross-channel decoupling (e.g., two redundant sensors suddenly drifting apart).

### How It Works:
Engine C was designed to measure Fisher-Z transformed correlation coefficients across rolling windows. It is currently parked/dormant because baseline correlations in the magnetometer triad proved too unstable across different orbital phases (e.g., sunlight vs. eclipse), leading to unreliable detection thresholds.

---

## The Unified Decision Gate & Streaming Integration
In the live event loop (located in `backend/api.py`), incoming 1 Hz telemetry is simultaneously evaluated by both Engine A and Engine B.

*   **Logical OR:** If *either* Engine A (flatline) or Engine B (physics spike) triggers an alarm, the Unified Gate raises an anomaly.
*   **Incident Latching:** Once an anomaly is triggered, a rising-edge latch (`incident_in_progress`) is set. This guarantees that SENTINEL emits exactly one `sentinel_alert` payload to the WebSocket frontend per incident, preventing the UI and downstream LLM diagnostic threads from being flooded while the anomaly persists.
