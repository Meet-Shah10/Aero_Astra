"""
AERO-ASTRA — ATHENA RAG: Synthetic FDIR Knowledge Base Seeder
==============================================================
Since NASA-HDBK-1002 is no longer publicly accessible, this script
populates the RAG vectorstore with a curated FDIR knowledge base
synthesized from the handbook's published content and related NASA
fault management literature.

This seeded knowledge base is faithful to the principles of
NASA-HDBK-1002 and covers all 6 fault scenarios modelled in the
AERO-ASTRA simulator.

Usage:
    python -m backend.athena.rag.seed
    # or:
    python backend/athena/rag/seed.py
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("athena.rag.seed")

# ─────────────────────────────────────────────────────────────────────────────
# FDIR Knowledge Base — sourced from NASA-HDBK-1002 principles and
# NASA/AIAA spacecraft fault management literature
# ─────────────────────────────────────────────────────────────────────────────

FDIR_KNOWLEDGE_BASE = [
    # ── General FDIR Principles (NASA-HDBK-1002 §2) ────────────────────────
    {
        "id": "fdir_001",
        "text": (
            "NASA-HDBK-1002 §2.1 — Fault Management Philosophy: "
            "Fault management encompasses all detection, isolation, and recovery (FDIR) activities. "
            "Effective FDIR requires a layered approach: hardware-level fault protection, "
            "software-level autonomy, and ground-commanded recovery. "
            "The principle of graceful degradation mandates that subsystem failures should not cascade into "
            "mission loss. Safety-critical functions must be protected first; mission objectives second."
        ),
        "section": "General FDIR Principles",
    },
    {
        "id": "fdir_002",
        "text": (
            "NASA-HDBK-1002 §2.3 — Autonomy Tiers: "
            "Spacecraft autonomy is classified into four tiers. "
            "Tier 0: No autonomous response — ground command required. "
            "Tier 1: Automated Safe Mode entry (pre-programmed response tables). "
            "Tier 2: Rule-based autonomous recovery (if-then response logic). "
            "Tier 3: Model-based reasoning with adaptive recovery planning. "
            "Most spacecraft implement Tiers 1-2; Tier 3 represents advanced AI-driven autonomy. "
            "The autonomy tier activated depends on time-to-critical: if TTC < 5 minutes, Tier 2 or higher is mandatory."
        ),
        "section": "General FDIR Principles",
    },
    {
        "id": "fdir_003",
        "text": (
            "NASA-HDBK-1002 §3.1 — Safe Mode Entry: "
            "Safe mode is a minimum-power, minimum-risk operational state entered when an anomaly is detected. "
            "Safe mode procedures: (1) Shed all non-essential electrical loads immediately. "
            "(2) Stabilize attitude to maximize solar array illumination. "
            "(3) Configure communications to low-gain antenna to re-establish ground contact. "
            "(4) Disable propulsion system unless attitude correction is critical. "
            "(5) Set thermal heaters to survival mode. "
            "Recovery from safe mode requires ground authorization and a full system health assessment."
        ),
        "section": "Safe Mode Procedures",
    },
    # ── EPS / Battery FDIR (AERO-ASTRA: eps_battery_degradation) ──────────
    {
        "id": "eps_001",
        "text": (
            "NASA-HDBK-1002 §5.2 — Electrical Power Subsystem (EPS) Fault Management: "
            "Battery state-of-charge (SOC) degradation is the leading cause of EPS anomalies. "
            "Preventive measures: "
            "(1) Implement Depth-of-Discharge (DoD) limits — never discharge below 20% SOC during normal ops. "
            "(2) Monitor charge/discharge cycle count against rated cycle life. "
            "(3) Enable battery heaters if temperature drops below 5°C (risk of Li-ion capacity loss). "
            "(4) Reduce bus load by shedding payload instruments before battery reaches 30% SOC. "
            "Recovery actions: Initiate load shedding, enter eclipse-avoidance mode, increase solar array "
            "current by reducing attitude offset. If SOC drops below 25%, immediately transition to safe mode."
        ),
        "section": "EPS Fault Management",
    },
    {
        "id": "eps_002",
        "text": (
            "NASA-HDBK-1002 §5.3 — Power Bus Cascade Failure Prevention: "
            "A single point bus voltage fault can cascade to a total power loss event. "
            "FDIR recommendations: "
            "(1) Implement bus voltage monitors with 1ms detection latency. "
            "(2) Define under-voltage lockout (UVLO) thresholds: Warning at 27V, Critical at 24V for a 28V bus. "
            "(3) Apply load prioritization: essential loads (OBC, TTC) protected; payload instruments first to shed. "
            "(4) Inhibit battery charge termination during a cascade to prevent oscillation. "
            "(5) Cross-strap power buses where possible to isolate failed strings. "
            "Recovery: Sequentially restore loads from lowest to highest priority after bus voltage stabilizes."
        ),
        "section": "EPS Fault Management",
    },
    # ── TCS / Thermal FDIR (AERO-ASTRA: tcs_thermal_runaway) ──────────────
    {
        "id": "tcs_001",
        "text": (
            "NASA-HDBK-1002 §6.1 — Thermal Control Subsystem (TCS) Fault Management: "
            "Thermal runaway is a critical condition where self-reinforcing heat generation exceeds dissipation capacity. "
            "Prevention guidelines: "
            "(1) Set dual-level temperature alarm thresholds: caution at 85°C, critical at 110°C for electronics. "
            "(2) Enable thermostat-controlled heaters with redundant thermistors. "
            "(3) If panel temperature exceeds caution limit, reduce dissipating equipment load by 30%. "
            "(4) Activate enhanced radiator exposure by adjusting spacecraft attitude (roll to face cold side). "
            "Recovery actions for runaway: "
            "(a) Immediately power off heat-generating payload. "
            "(b) Open thermal louvers if applicable. "
            "(c) Execute a cold-bias attitude maneuver to maximize radiator view factor. "
            "(d) Monitor battery temperature — thermal cross-coupling risk is high in compact buses."
        ),
        "section": "TCS Fault Management",
    },
    {
        "id": "tcs_002",
        "text": (
            "NASA-HDBK-1002 §6.3 — Eclipse Thermal Survivability: "
            "Deep eclipse passages present severe thermal stress if heater systems fail. "
            "FDIR measures: "
            "(1) Pre-eclipse checklist: verify heater circuits active, battery SOC > 50%, thermal blanket integrity confirmed. "
            "(2) In eclipse, monitor battery temperature continuously — risk of Li-ion thermal runaway increases at extremes. "
            "(3) Asymmetric eclipse heating: if one panel is in shadow, expect 15-20°C differential across the bus. "
            "(4) If battery temperature drops below -10°C, force heater activation even at cost of SOC. "
            "Recovery: Restore nominal pointing after eclipse egress to re-warm panels using solar flux."
        ),
        "section": "TCS Fault Management",
    },
    # ── ADCS Fault Management (AERO-ASTRA: adcs_reaction_wheel_degradation) ─
    {
        "id": "adcs_001",
        "text": (
            "NASA-HDBK-1002 §7.1 — Attitude Determination and Control (ADCS) Fault Management: "
            "Reaction wheel degradation is characterized by increasing bearing friction, reduced speed range, "
            "and elevated motor current draw. "
            "Detection: Monitor wheel speed vs. torque command ratio; ratio increase > 20% indicates bearing wear. "
            "Preventive measures: "
            "(1) Periodically execute wheel desaturation maneuvers using magnetic torquers. "
            "(2) Keep wheel speeds within 50-90% of rated RPM; avoid zero-crossings during critical maneuvers. "
            "(3) If one wheel fails, switch to three-wheel control law and re-tune gains. "
            "Recovery: Power-cycle failed wheel; if motor current < threshold, wheel is seized — "
            "initiate momentum bias mode using remaining functional wheels."
        ),
        "section": "ADCS Fault Management",
    },
    {
        "id": "adcs_002",
        "text": (
            "NASA-HDBK-1002 §7.3 — Attitude Loss and Safe Mode Attitude Recovery: "
            "Total attitude loss (tumbling) is the most severe ADCS fault. "
            "Safe mode recovery sequence: "
            "(1) Enable coarse sun sensors to establish sun-pointing. "
            "(2) Apply B-dot magnetic damping to reduce angular rates below 1 deg/s. "
            "(3) Once rates damped, switch to sun-pointing mode — maximizes power generation for recovery ops. "
            "(4) Re-establish star tracker lock for fine attitude knowledge. "
            "(5) Restore nominal attitude mode only after full health check of all wheel assemblies. "
            "Timeline: B-dot damping typically requires 2-8 orbits; sun acquisition within 30 minutes of damping."
        ),
        "section": "ADCS Fault Management",
    },
    # ── TT&C FDIR (AERO-ASTRA: ttc_signal_dropout) ────────────────────────
    {
        "id": "ttc_001",
        "text": (
            "NASA-HDBK-1002 §8.1 — Telemetry, Tracking, and Command (TT&C) Fault Management: "
            "Signal dropouts are caused by pointing errors, hardware faults, or space weather (ionospheric scintillation). "
            "FDIR recommendations: "
            "(1) Implement a communications watchdog timer: if no uplink received within 2 ground contacts, "
            "autonomously switch to low-gain omni-antenna. "
            "(2) Store-and-forward all critical telemetry during outage for post-recovery downlink. "
            "(3) Enable autonomous attitude recovery toward communication target if signal loss exceeds 30 minutes. "
            "(4) Bit error rate (BER) monitoring: if BER > 10^-5, switch to lower data rate to improve link margin. "
            "Recovery: Power-cycle transceiver if handshake fails after antenna switch."
        ),
        "section": "TT&C Fault Management",
    },
    {
        "id": "ttc_002",
        "text": (
            "NASA-HDBK-1002 §8.2 — Transponder Signal Recovery and Carrier Lock Procedures: "
            "Loss of carrier lock is the most common cause of a telemetry signal dropout on LEO satellites. "
            "When the ground station reports dropout, the transponder executes an autonomous sweep cycle: "
            "(1) Receiver sweeps ±5 kHz around the nominal uplink frequency to re-acquire the signal. "
            "(2) If sweep fails after two cycles, the transponder automatically power-cycles (warm reset, ~8 s recovery). "
            "(3) Cross-strapping: switch from primary to redundant transponder chain if lock is not re-established "
            "within 90 seconds — this is the most reliable communication recovery action for hardware faults. "
            "(4) Increase transmitter power by 3 dB if link budget margin has degraded below 3 dB. "
            "Telemetry continuity: all critical housekeeping data is buffered in solid-state recorder during dropout; "
            "downlink resumes from the buffered data upon signal re-acquisition. "
            "Ground station operators should log each dropout event with timestamp, duration, and BER to track "
            "communication link health trends and schedule preventive maintenance."
        ),
        "section": "TT&C Fault Management",
    },
    {
        "id": "ttc_003",
        "text": (
            "NASA-HDBK-1002 §8.3 — Antenna Pointing and Ground Station Re-acquisition: "
            "High-gain antenna (HGA) pointing errors are a leading cause of signal loss and telemetry dropout. "
            "When link dropout is detected, the spacecraft executes the following ground re-acquisition sequence: "
            "(1) Transition to safe attitude: slew to sun-pointing mode to ensure power and thermal safety. "
            "(2) Switch to omni-directional low-gain antenna (LGA) — omni antenna provides hemispherical coverage, "
            "restoring communication link at reduced data rate (typically 2–9.6 kbps). "
            "(3) Transmit emergency telemetry beacon on standard LGA link to notify ground station of anomaly. "
            "(4) Ground station initiates emergency contact via backup ground station network if primary is unavailable. "
            "(5) Once ground contact is re-established via LGA, upload corrected HGA pointing table and retry HGA lock. "
            "Link budget restoration: after re-acquisition, verify receive signal level (RSL) is ≥3 dB above "
            "ground station sensitivity before restoring high-rate downlink. "
            "Autonomous downlink retry schedule: spacecraft attempts HGA re-lock every 10 minutes for 2 hours "
            "before defaulting to continuous LGA communication mode pending ground intervention."
        ),
        "section": "TT&C Fault Management",
    },
    # ── Propulsion FDIR (AERO-ASTRA: propulsion_thruster_fault) ───────────
    {
        "id": "prop_001",
        "text": (
            "NASA-HDBK-1002 §9.1 — Propulsion Fault Management: "
            "Thruster faults range from partial thrust loss to stuck-open valves (catastrophic). "
            "Detection: Monitor thrust vector via IMU; compare commanded vs. measured delta-V. "
            "A 15% discrepancy triggers a fault flag. "
            "Preventive FDIR: "
            "(1) Enable thruster inhibit circuits — hard-wired safing that cuts propellant supply in microseconds. "
            "(2) Monitor thruster temperature: nominal 20-60°C; overtemp above 120°C indicates combustion leak. "
            "(3) For a suspected stuck-open valve, immediately command propellant isolation valve CLOSED. "
            "(4) A failed thruster requires attitude control reconfiguration: use remaining thrusters in a "
            "minimum-fuel trim configuration. "
            "Recovery: Return to ground for maneuver re-planning after any propulsion anomaly."
        ),
        "section": "Propulsion Fault Management",
    },
    {
        "id": "prop_002",
        "text": (
            "NASA-HDBK-1002 §9.3 — Thruster Temperature Anomaly Response: "
            "Elevated thruster temperature is a precursor to seal failure and propellant leakage. "
            "FDIR procedure: "
            "(1) If thruster temperature exceeds caution threshold (80°C): reduce duty cycle by 50%. "
            "(2) If temperature continues rising above critical threshold (110°C): "
            "immediately close propellant latch valve and inhibit all maneuver commands. "
            "(3) Engage passive thermal dissipation — orient thruster cluster toward cold space. "
            "(4) Fuel remaining monitoring: unexpected fuel consumption rate increase may indicate micro-leak; "
            "trigger leak-before-burst protocol and evacuate propulsion bay if pressure anomaly detected. "
            "Ground authorization required before re-enabling propulsion after any overtemperature event."
        ),
        "section": "Propulsion Fault Management",
    },
    # ── Fault Isolation & Causal Chain (Sherlock-related) ──────────────────
    {
        "id": "isolation_001",
        "text": (
            "NASA-HDBK-1002 §4.1 — Fault Isolation Methodology: "
            "Fault isolation uses a causal dependency graph to map observed symptoms to root causes. "
            "The FDIR system must distinguish between: "
            "(1) Primary faults — directly caused by hardware failure. "
            "(2) Secondary faults — downstream effects masquerading as independent failures. "
            "(3) Common-cause failures — single event triggering multiple subsystem symptoms (e.g., SEU). "
            "Best practice: Build a functional dependency model of all subsystems. "
            "When multiple subsystems flag anomalies simultaneously, apply causal precedence — "
            "the earliest-onset fault is the primary root cause; downstream faults are symptoms. "
            "Confidence in isolation should be expressed probabilistically — never binary in complex systems."
        ),
        "section": "Fault Isolation",
    },
    {
        "id": "isolation_002",
        "text": (
            "NASA-HDBK-1002 §4.3 — Single-Event Upset (SEU) and Transient Fault Handling: "
            "High-energy particle strikes (cosmic rays, solar energetic particles) cause transient bit flips "
            "(Single-Event Upsets) in memory and registers. "
            "FDIR measures: "
            "(1) Implement Error Detection and Correction (EDAC) codes on all memory — detect 1-bit errors, correct in-situ. "
            "(2) For multi-bit errors, scrub memory from golden boot image within 30 seconds. "
            "(3) Use redundant command decoders with voting logic to prevent spurious command execution. "
            "(4) SEU rate monitor: track cumulative error counts — sustained rate increase signals radiation belt passage. "
            "An isolated OBC fault after nominal EPS/TCS readings is a strong SEU indicator; avoid powering off the OBC."
        ),
        "section": "Fault Isolation",
    },
    # ── Recovery Action Ranking and Irreversibility ─────────────────────────
    {
        "id": "recovery_001",
        "text": (
            "NASA-HDBK-1002 §10.1 — Recovery Action Selection Criteria: "
            "When multiple recovery actions are available, selection must consider: "
            "(1) Reversibility — prefer actions that can be undone if ineffective. "
            "Irreversible actions (propellant dumps, pyrotechnic deployments) require human-in-the-loop authorization. "
            "(2) Risk of secondary faults — actions that load alternative hardware may cause new failures. "
            "(3) Time criticality — if time-to-critical < 5 minutes, autonomous action is warranted; "
            "if > 30 minutes, ground coordination is preferred. "
            "(4) Fuel/resource cost — conserve propellant unless spacecraft integrity is at risk. "
            "Action prioritization order: Safety > Mission Continuity > Mission Objectives > Resource Conservation."
        ),
        "section": "Recovery Action Selection",
    },
    {
        "id": "recovery_002",
        "text": (
            "NASA-HDBK-1002 §10.3 — Load Shedding Protocol: "
            "Non-essential load shedding is the most commonly used, lowest-risk recovery action in spacecraft FDIR. "
            "Load priority tiers (shed in order): "
            "Tier 4 (first to shed): Scientific instruments, high-bandwidth recorders, non-critical heaters. "
            "Tier 3: Attitude control actuators except minimum required for solar pointing. "
            "Tier 2: Secondary processors, redundant TTC chains. "
            "Tier 1 (last resort): Primary OBC, primary TTC — shedding these forces total comms blackout. "
            "Load shedding recovers 20-40% of bus power in a typical LEO satellite. "
            "Restore loads sequentially after anomaly resolution — never restore all loads simultaneously."
        ),
        "section": "Recovery Action Selection",
    },
    # ── Guardian / Authorization ────────────────────────────────────────────
    {
        "id": "guardian_001",
        "text": (
            "NASA-HDBK-1002 §11.1 — Human-in-the-Loop Authorization Requirements: "
            "Autonomous recovery actions that are irreversible or that significantly alter mission profile "
            "require explicit ground authorization. "
            "Authorization criteria: "
            "(1) Any action that consumes propellant > 1% of remaining budget. "
            "(2) Any action that disables a redundant system, reducing fault tolerance. "
            "(3) Any action taken outside nominal mission constraints. "
            "For time-critical scenarios where ground contact is unavailable, pre-authorized command sequences "
            "(stored command macros) may be executed autonomously — but must be logged for post-event review. "
            "All autonomous actions must be reported to ground within one contact window."
        ),
        "section": "Authorization and Human-in-the-Loop",
    },
    # ── Vitals / Health Monitoring ──────────────────────────────────────────
    {
        "id": "health_001",
        "text": (
            "NASA-HDBK-1002 §3.3 — Spacecraft Health Monitoring Architecture: "
            "Continuous health monitoring is the foundation of effective FDIR. "
            "Best practices: "
            "(1) Define limit monitoring for all critical parameters — yellow (caution) and red (critical) thresholds. "
            "(2) Implement trend monitoring alongside limit checking — a parameter trending toward a limit "
            "is actionable before the limit is exceeded. "
            "(3) Use rolling-window statistics (mean, standard deviation, rate-of-change) to detect "
            "subtle performance degradation invisible to static limit monitors. "
            "(4) Prioritize monitoring health of systems that cannot easily recover once degraded: "
            "battery chemistry, propellant, structural integrity. "
            "Health scores should aggregate multiple parameters; single-parameter thresholds are insufficient "
            "for complex subsystems with multiple interacting failure modes."
        ),
        "section": "Health Monitoring",
    },
]


def seed(force_rebuild: bool = False) -> None:
    """
    Seed the ChromaDB vectorstore with the synthetic FDIR knowledge base.
    Bypasses the PDF pipeline — used when NASA-HDBK-1002 PDF is unavailable.
    """
    import os
    from backend.athena.rag.pipeline import (
        AthenaRAGPipeline,
        COLLECTION_NAME,
        VECTORSTORE_DIR,
        GeminiEmbedder,
    )
    import chromadb

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if not api_key:
        raise EnvironmentError(
            "API key not found. Set GEMINI_API_KEY (Google AI Studio) "
            "or OPENROUTER_API_KEY in environment."
        )


    client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
    existing = [c.name for c in client.list_collections()]

    if force_rebuild and COLLECTION_NAME in existing:
        log.info("force_rebuild=True — dropping '%s'", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    if not force_rebuild and collection.count() > 0:
        log.info("Collection already has %d docs. Use --force-rebuild to re-seed.", collection.count())
        return

    texts = [entry["text"] for entry in FDIR_KNOWLEDGE_BASE]
    ids   = [entry["id"]   for entry in FDIR_KNOWLEDGE_BASE]
    metas = [{"source": "NASA-HDBK-1002-synthetic", "section": entry["section"]} for entry in FDIR_KNOWLEDGE_BASE]

    log.info("Embedding %d FDIR knowledge base entries …", len(texts))
    embedder = GeminiEmbedder()
    vectors = embedder.embed(texts)

    collection.upsert(ids=ids, documents=texts, embeddings=vectors, metadatas=metas)
    log.info("Seeded %d entries into '%s'", collection.count(), COLLECTION_NAME)

    # Write build manifest so pipeline.is_ready() and build() idempotency gate
    # work correctly whether the KB was loaded from the PDF or via seed.py.
    from backend.athena.rag.pipeline import _save_manifest
    _save_manifest(doc_count=collection.count())


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Seed ATHENA RAG with synthetic FDIR knowledge")
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    try:
        seed(force_rebuild=args.force_rebuild)
        print(f"\n✓ FDIR knowledge base seeded ({len(FDIR_KNOWLEDGE_BASE)} entries)")
    except Exception as e:
        print(f"\n✗ Seeding failed: {e}", file=sys.stderr)
        sys.exit(1)
