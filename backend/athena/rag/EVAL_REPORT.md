# ATHENA RAG — Full FDIR Evaluation Suite

> **Generated:** 2026-09-04 12:38 UTC  
> **Top-K:** 4  
> **Queries evaluated:** 7  
> **Vector store:** ChromaDB (`nasa_hdbk_1002`)  
> **Embedding model:** `openai/text-embedding-3-small` via OpenRouter

---

## Aggregate Metrics

| Metric | Value | Target | Status |
|---|---|---|---|
| **Hit Rate @4** | 100.0% | ≥ 80% | ✅ |
| **Precision @4** | 0.643 | ≥ 0.30 | ✅ |
| **Recall @4** | 0.786 | ≥ 0.30 | ✅ |
| **MRR @4** | 1.000 | ≥ 0.70 | ✅ |
| **Avg Relevance** | 0.572 | ≥ 0.40 | ✅ |
| **Avg Latency** | 1123.2 ms | ≤ 1000 ms | ❌ |

> **Relevance criterion:** A passage is judged relevant if it contains ≥ 2 of the
> ground-truth keywords for that fault scenario (case-insensitive substring match).
> **Recall denominator:** number of expected relevant handbook sections per fault.

---

## Per-Fault Summary

| Fault | Hit | RR | P@4 | R@4 | Avg Sim | Latency | Keywords Matched |
|---|---|---|---|---|---|---|---|
| **TCS Thermal Runaway** | ✅ | 1.00 | 1.00 | 1.00 | 0.551 | 1905 ms | `thermal`, `temperature`, `heater`, `TCS`, `eclipse` |
| **TT&C Signal Dropout** | ✅ | 1.00 | 0.75 | 1.00 | 0.565 | 1006 ms | `communication`, `telemetry`, `signal`, `link`, `ground` |
| **Propulsion Thruster Fault** | ✅ | 1.00 | 0.50 | 0.67 | 0.580 | 532 ms | `thruster`, `propulsion`, `fuel`, `maneuver`, `fault` |
| **EPS Battery Degradation** | ✅ | 1.00 | 0.50 | 0.50 | 0.581 | 1036 ms | `battery`, `power`, `charge`, `EPS`, `degradation` |
| **ADCS Reaction Wheel Fault** | ✅ | 1.00 | 0.50 | 0.67 | 0.587 | 1103 ms | `attitude`, `ADCS`, `reaction wheel`, `momentum`, `desaturation` |
| **EPS Cascade Power Failure** | ✅ | 1.00 | 0.75 | 1.00 | 0.541 | 1243 ms | `power`, `bus`, `voltage`, `load`, `shedding` |
| **General FDIR Principles** | ✅ | 1.00 | 0.50 | 0.67 | 0.597 | 1037 ms | `FDIR`, `detection`, `isolation`, `recovery` |

---

## Per-Fault Detailed Results

### TCS Thermal Runaway — `tcs_thermal_runaway` ✅ HIT

**Query sent to vectorstore:**
> thermal runaway satellite temperature exceeding limits heater circuit failure TCS eclipse battery temperature HIGH

**Expected relevant handbook sections:** §6.1, §6.2, §6.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 1.0000 |
| Recall@4 | 1.0000 |
| Avg Cosine Similarity | 0.5505 |
| Relevant passages in top-4 | 4 / 4 |
| Retrieval latency | 1904.5 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.660 | ✅ | NASA-HDBK-1002 §6.1 — Thermal Control Subsystem (TCS) Fault Management: Thermal runaway is a critical condition where self-reinforcing heat generation… |
| 2 | 0.617 | ✅ | NASA-HDBK-1002 §6.3 — Eclipse Thermal Survivability: Deep eclipse passages present severe thermal stress if heater systems fail. FDIR measures: (1) Pr… |
| 3 | 0.495 | ✅ | NASA-HDBK-1002 §9.3 — Thruster Temperature Anomaly Response: Elevated thruster temperature is a precursor to seal failure and propellant leakage. FDIR… |
| 4 | 0.430 | ✅ | NASA-HDBK-1002 §5.2 — Electrical Power Subsystem (EPS) Fault Management: Battery state-of-charge (SOC) degradation is the leading cause of EPS anomali… |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `tcs_thermal_runaway` fault scenario at rank 1/1.
Keywords matched: `thermal`, `temperature`, `heater`, `TCS`, `eclipse`.

---

### TT&C Signal Dropout — `ttc_signal_dropout` ✅ HIT

**Query sent to vectorstore:**
> telemetry signal loss communication dropout ground station link TTC uplink downlink degradation MEDIUM

**Expected relevant handbook sections:** §8.1, §8.2, §8.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.7500 |
| Recall@4 | 1.0000 |
| Avg Cosine Similarity | 0.5646 |
| Relevant passages in top-4 | 3 / 4 |
| Retrieval latency | 1006.4 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.682 | ✅ | NASA-HDBK-1002 §8.1 — Telemetry, Tracking, and Command (TT&C) Fault Management: Signal dropouts are caused by pointing errors, hardware faults, or spa… |
| 2 | 0.624 | ✅ | NASA-HDBK-1002 §8.2 — Transponder Signal Recovery and Carrier Lock Procedures: Loss of carrier lock is the most common cause of a telemetry signal dro… |
| 3 | 0.551 | ✅ | NASA-HDBK-1002 §8.3 — Antenna Pointing and Ground Station Re-acquisition: High-gain antenna (HGA) pointing errors are a leading cause of signal loss a… |
| 4 | 0.402 | — | NASA-HDBK-1002 §10.3 — Load Shedding Protocol: Non-essential load shedding is the most commonly used, lowest-risk recovery action in spacecraft FDIR. … |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `ttc_signal_dropout` fault scenario at rank 1/1.
Keywords matched: `communication`, `telemetry`, `signal`, `link`, `ground`.

---

### Propulsion Thruster Fault — `propulsion_thruster_fault` ✅ HIT

**Query sent to vectorstore:**
> thruster anomaly propulsion fault attitude disturbance fuel leak maneuver abort spacecraft safing HIGH

**Expected relevant handbook sections:** §7.1, §7.2, §7.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.5000 |
| Recall@4 | 0.6667 |
| Avg Cosine Similarity | 0.5800 |
| Relevant passages in top-4 | 2 / 4 |
| Retrieval latency | 532.2 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.676 | ✅ | NASA-HDBK-1002 §9.1 — Propulsion Fault Management: Thruster faults range from partial thrust loss to stuck-open valves (catastrophic). Detection: Moni… |
| 2 | 0.619 | ✅ | NASA-HDBK-1002 §9.3 — Thruster Temperature Anomaly Response: Elevated thruster temperature is a precursor to seal failure and propellant leakage. FDIR… |
| 3 | 0.522 | — | NASA-HDBK-1002 §3.1 — Safe Mode Entry: Safe mode is a minimum-power, minimum-risk operational state entered when an anomaly is detected. Safe mode pro… |
| 4 | 0.503 | — | NASA-HDBK-1002 §7.3 — Attitude Loss and Safe Mode Attitude Recovery: Total attitude loss (tumbling) is the most severe ADCS fault. Safe mode recovery … |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `propulsion_thruster_fault` fault scenario at rank 1/1.
Keywords matched: `thruster`, `propulsion`, `fuel`, `maneuver`, `fault`.

---

### EPS Battery Degradation — `eps_battery_degradation` ✅ HIT

**Query sent to vectorstore:**
> battery state-of-charge degradation EPS power bus low voltage load shedding solar array eclipse HIGH

**Expected relevant handbook sections:** §5.1, §5.2, §5.3, §10.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.5000 |
| Recall@4 | 0.5000 |
| Avg Cosine Similarity | 0.5807 |
| Relevant passages in top-4 | 2 / 4 |
| Retrieval latency | 1035.9 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.711 | ✅ | NASA-HDBK-1002 §5.2 — Electrical Power Subsystem (EPS) Fault Management: Battery state-of-charge (SOC) degradation is the leading cause of EPS anomali… |
| 2 | 0.579 | — | NASA-HDBK-1002 §6.3 — Eclipse Thermal Survivability: Deep eclipse passages present severe thermal stress if heater systems fail. FDIR measures: (1) Pr… |
| 3 | 0.532 | ✅ | NASA-HDBK-1002 §5.3 — Power Bus Cascade Failure Prevention: A single point bus voltage fault can cascade to a total power loss event. FDIR recommendat… |
| 4 | 0.500 | — | NASA-HDBK-1002 §10.3 — Load Shedding Protocol: Non-essential load shedding is the most commonly used, lowest-risk recovery action in spacecraft FDIR. … |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `eps_battery_degradation` fault scenario at rank 1/1.
Keywords matched: `battery`, `power`, `charge`, `EPS`, `degradation`.

---

### ADCS Reaction Wheel Fault — `adcs_reaction_wheel` ✅ HIT

**Query sent to vectorstore:**
> reaction wheel failure attitude control ADCS momentum desaturation tumbling spacecraft pointing loss MEDIUM

**Expected relevant handbook sections:** §4.1, §4.2, §4.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.5000 |
| Recall@4 | 0.6667 |
| Avg Cosine Similarity | 0.5867 |
| Relevant passages in top-4 | 2 / 4 |
| Retrieval latency | 1103.5 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.682 | ✅ | NASA-HDBK-1002 §7.3 — Attitude Loss and Safe Mode Attitude Recovery: Total attitude loss (tumbling) is the most severe ADCS fault. Safe mode recovery … |
| 2 | 0.657 | ✅ | NASA-HDBK-1002 §7.1 — Attitude Determination and Control (ADCS) Fault Management: Reaction wheel degradation is characterized by increasing bearing fr… |
| 3 | 0.505 | — | NASA-HDBK-1002 §9.1 — Propulsion Fault Management: Thruster faults range from partial thrust loss to stuck-open valves (catastrophic). Detection: Moni… |
| 4 | 0.503 | — | NASA-HDBK-1002 §8.1 — Telemetry, Tracking, and Command (TT&C) Fault Management: Signal dropouts are caused by pointing errors, hardware faults, or spa… |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `adcs_reaction_wheel` fault scenario at rank 1/1.
Keywords matched: `attitude`, `ADCS`, `reaction wheel`, `momentum`, `desaturation`.

---

### EPS Cascade Power Failure — `eps_cascade_failure` ✅ HIT

**Query sent to vectorstore:**
> power bus cascade failure under-voltage lockout load priority EPS total power loss recovery

**Expected relevant handbook sections:** §5.3, §10.3

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.7500 |
| Recall@4 | 1.0000 |
| Avg Cosine Similarity | 0.5414 |
| Relevant passages in top-4 | 3 / 4 |
| Retrieval latency | 1243.2 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.709 | ✅ | NASA-HDBK-1002 §5.3 — Power Bus Cascade Failure Prevention: A single point bus voltage fault can cascade to a total power loss event. FDIR recommendat… |
| 2 | 0.515 | ✅ | NASA-HDBK-1002 §5.2 — Electrical Power Subsystem (EPS) Fault Management: Battery state-of-charge (SOC) degradation is the leading cause of EPS anomali… |
| 3 | 0.497 | ✅ | NASA-HDBK-1002 §10.3 — Load Shedding Protocol: Non-essential load shedding is the most commonly used, lowest-risk recovery action in spacecraft FDIR. … |
| 4 | 0.445 | — | NASA-HDBK-1002 §4.3 — Single-Event Upset (SEU) and Transient Fault Handling: High-energy particle strikes (cosmic rays, solar energetic particles) cau… |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `eps_cascade_failure` fault scenario at rank 1/1.
Keywords matched: `power`, `bus`, `voltage`, `load`, `shedding`.

---

### General FDIR Principles — `general_fdir` ✅ HIT

**Query sent to vectorstore:**
> fault detection isolation recovery FDIR autonomy design principles spacecraft safe mode transition

**Expected relevant handbook sections:** §2.1, §2.2, §3.1

**Metrics:**

| Metric | Value |
|---|---|
| Reciprocal Rank | 1.0000 |
| Precision@4 | 0.5000 |
| Recall@4 | 0.6667 |
| Avg Cosine Similarity | 0.5971 |
| Relevant passages in top-4 | 2 / 4 |
| Retrieval latency | 1037.0 ms |

**Retrieved passages (top-4):**

| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |
|---|---|---|---|
| 1 | 0.689 | ✅ | NASA-HDBK-1002 §2.1 — Fault Management Philosophy: Fault management encompasses all detection, isolation, and recovery (FDIR) activities. Effective FD… |
| 2 | 0.583 | — | NASA-HDBK-1002 §3.1 — Safe Mode Entry: Safe mode is a minimum-power, minimum-risk operational state entered when an anomaly is detected. Safe mode pro… |
| 3 | 0.564 | ✅ | NASA-HDBK-1002 §4.1 — Fault Isolation Methodology: Fault isolation uses a causal dependency graph to map observed symptoms to root causes. The FDIR sy… |
| 4 | 0.553 | — | NASA-HDBK-1002 §11.1 — Human-in-the-Loop Authorization Requirements: Autonomous recovery actions that are irreversible or that significantly alter mis… |

**Interpretation:** Retrieval succeeded. The vectorstore returned at least one
passage matching the `general_fdir` fault scenario at rank 1/1.
Keywords matched: `FDIR`, `detection`, `isolation`, `recovery`.

---

## Notes & Next Steps

- **Synthetic KB:** Results are based on the 18-entry synthetic FDIR knowledge base.
  Ingesting the real NASA-HDBK-1002 PDF will increase vocabulary diversity and
  is expected to improve Avg Relevance above 0.60.
- **Precision denominator:** `K` passages retrieved per query. Low Precision@K with
  high Hit Rate means relevant passages exist but so do off-topic ones.
- **Recall denominator:** number of `relevant_sections` listed per fault (a lower bound).
  Actual recall against a full golden set may differ.
- **RAGAS integration:** For a full RAGAS-framework evaluation (faithfulness, answer
  relevancy, context precision), see the [RAGAS docs](https://docs.ragas.io/).
  The `EvalReport` structure is compatible with RAGAS dataset format.

*Report auto-generated by `backend/athena/rag/evaluate.py` — 2026-09-04 12:38 UTC*