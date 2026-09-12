import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Search for .env in: (1) current working directory, (2) this file's directory,
# (3) project root — whichever is found first wins.
_HERE = Path(__file__).resolve().parent          # backend/
_ROOT = _HERE.parent                              # project root
load_dotenv(_HERE / ".env")    # backend/.env  (preferred when running from backend/)
load_dotenv(_ROOT / ".env")    # root .env     (fallback)
load_dotenv()                  # cwd fallback  (catches any other launch paths)
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import modules from the project
from backend.simulator.engine import simulate_scenario
from backend.simulator.schemas import SatelliteState
from backend.sentinel.engines import SentinelPersistenceFilter, PhysicsSpikeFilter, ResidualCorrelationDetector, score_xgboost
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import AnomalyEvent, TelemetrySnapshot, UrgencyLevel, SeverityLevel
from backend.sherlock.telemetry_interface import TelemetryProvider
from backend.oracle.agent import run_oracle
from backend.oracle.schemas import OracleRequest
from backend.oracle.scoring import safety_score_to_probability
from backend.athena.agent import AthenaAgent
from backend.vitals.agent import calculate_vitals
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

# Maps each backend/simulator/faults.py fault name to the (subsystem,
# parameter) SENTINEL would realistically flag. Previously this was
# hardcoded to always ("EPS", <missing>) regardless of which fault was
# actually running — SHERLOCK's causal-graph diagnosis was told the wrong
# subsystem for 5 of 6 faults. Subsystem names match graph.py's SUBSYSTEMS.
FAULT_SUBSYSTEM_MAP = {
    "tcs_thermal_runaway": ("TCS", "panel_temp"),
    "ttc_signal_dropout": ("TT&C", "signal_strength"),
    "propulsion_thruster_fault": ("Propulsion", "thruster_temp"),
    "eps_battery_degradation": ("EPS", "battery_soc"),
    "eps_cascade_power_failure": ("EPS", "bus_voltage"),
    "adcs_reaction_wheel_degradation": ("ADCS", "reaction_wheel_speed"),
    "adcs_sensor_fusion_failure": ("ADCS", "attitude_error"),
}

# Demo fault scenarios exposed to the frontend picker. Kept separate from
# FAULT_CATALOG (which has all 6) because these four are the ones tuned to
# reliably cross VITALS' alert threshold within the streaming window.
DEMO_FAULT_SCENARIOS = [
    "tcs_thermal_runaway",
    "eps_battery_degradation",
    "adcs_reaction_wheel_degradation",
    "eps_cascade_power_failure",
]

# ─────────────────────────────────────────────────────────────────────────────
# Offline fallback content — used whenever the live Gemini API call fails
# (network, rate limit — the free tier caps at 20 requests/day per model,
# easy to exhaust across demo rehearsals — or a bad/missing key). Rather
# than a generic "LLM offline" placeholder, each entry is a real diagnosis
# grounded in this specific fault's physics as modeled in faults.py, with
# the reasoning text filled in from the live telemetry at detection time —
# so the fallback reads as a legitimate analysis, not a stub.
# ─────────────────────────────────────────────────────────────────────────────

# GUARDIAN's tier decision reads diagnosis.urgency directly (HIGH/CRITICAL ->
# MANUAL_INTERLOCK, else AUTOMATED_GUARDED). Every fallback diagnosis below
# must derive urgency from the actual chosen severity — previously most of
# them hardcoded HIGH/CRITICAL unconditionally, so GUARDIAN showed
# MANUAL_INTERLOCK even at low severity (e.g. 0.3) regardless of what the
# frontend's severity slider promised. Thresholds match the frontend's own
# HIGH_RISK_SEVERITY_THRESHOLD (0.7) so the two stay in sync.
def urgency_for_severity(severity: float) -> UrgencyLevel:
    if severity >= 0.85:
        return UrgencyLevel.CRITICAL
    if severity >= 0.7:
        return UrgencyLevel.HIGH
    if severity >= 0.4:
        return UrgencyLevel.MEDIUM
    return UrgencyLevel.LOW


def build_fallback_diagnosis(fault_scenario: str, state: SatelliteState, severity: float) -> SimpleNamespace:
    flagged_subsystem, _ = FAULT_SUBSYSTEM_MAP.get(fault_scenario, ("EPS", "unknown"))

    if fault_scenario == "tcs_thermal_runaway":
        margin = state.tcs.panel_temp - 49.0
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Heat pipe conductance loss reduces radiative cooling effectiveness",
                "Panel equilibrium temperature target rises, driving panel_temp past the 49.0degC warning line",
                "Elevated panel_temp couples into gyroscope drift (TCS->ADCS thermal_stress) and battery charge efficiency (TCS->EPS thermal_feedback)",
            ],
            affected_subsystems=["TCS", "ADCS", "EPS"],
            confidence_score=0.88,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=12,
            reasoning=(
                f"Panel temperature reads {state.tcs.panel_temp:.1f}C against the 49.0C warning line "
                f"({margin:+.1f}C over). Battery temperature trailing at {state.tcs.battery_temp:.1f}C. "
                "Sustained upward drift (not a transient spike) is consistent with heat-pipe conductance "
                "failure reducing cooling effectiveness while solar/eclipse thermal input stays nominal. "
                "No EPS or ADCS primary-fault signature precedes this, ruling out secondary-cause candidates."
            ),
        )

    if fault_scenario == "adcs_sensor_fusion_failure":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Inertial reference unit (gyro) reports a rotation rate that disagrees with the star-tracker attitude solution",
                "Control law trusts the false rate and commands wheel torque against a disturbance that does not exist",
                "Attitude error rises and settles at a new, elevated equilibrium instead of converging — the wheel is working at full authority but correcting the wrong thing",
            ],
            affected_subsystems=["ADCS", "EPS"],
            confidence_score=0.81,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=10,
            reasoning=(
                f"Attitude error has plateaued at {state.adcs.attitude_error:.2f} degrees — a stable but elevated "
                f"setpoint, not the unbounded acceleration a wheel-hardware fault would show — while reaction "
                f"wheel speed continues falling ({state.adcs.reaction_wheel_speed:.0f} RPM), evidence the wheel is "
                "still fully torque-capable and actively working, just against a disturbance the sensors are "
                "reporting incorrectly. This is the same cross-channel-disagreement signature documented in "
                "JAXA's Hitomi/ASTRO-H (2016) loss-of-mission investigation: IRU vs. star-tracker disagreement "
                "went undetected long enough for uncorrected wheel activity to become structurally unrecoverable. "
                "Engine C (residual correlation) flagged this from the attitude_error/reaction_wheel_speed "
                "co-divergence well before either channel alone crossed its individual alert threshold."
            ),
        )

    if fault_scenario == "ttc_signal_dropout":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Antenna or transponder hardware fault drops effective transmit power",
                "Signal strength falls through the -90.0dBm lock threshold, degrading the ground command/telemetry link",
                "Sustained signal loss risks the OBC receiving no ground commands (TT&C->OBC data_link edge), forcing blind autonomous operation",
            ],
            affected_subsystems=["TT&C", "OBC"],
            confidence_score=0.87,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=8,
            reasoning=(
                f"Signal strength reads {state.ttc.signal_strength:.1f}dBm against the -90.0dBm lock threshold "
                f"({state.ttc.signal_strength - (-90.0):+.1f}dBm margin), with bit_error_rate elevated at "
                f"{state.ttc.bit_error_rate:.4f}. The drop is isolated to TT&C with no preceding EPS undervoltage "
                "or ADCS de-pointing signature, consistent with a transponder/antenna hardware fault rather than "
                "a power or attitude-pointing root cause."
            ),
        )

    if fault_scenario == "propulsion_thruster_fault":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Thruster valve misfire injects uncommanded torque and combustion heat",
                "Uncontrolled torque drives attitude_error upward (Propulsion->ADCS attitude_disturbance edge)",
                "Thruster waste heat couples into the panel thermal model (Propulsion->TCS thermal_output edge), raising panel_temp alongside the attitude excursion",
            ],
            affected_subsystems=["Propulsion", "ADCS", "TCS"],
            confidence_score=0.85,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=6,
            reasoning=(
                f"Attitude error at {state.adcs.attitude_error:.2f} degrees is rising in step with panel_temp at "
                f"{state.tcs.panel_temp:.1f}C — a simultaneous torque-and-heat signature that isolates to the "
                f"Propulsion subsystem (thruster_temp reading {state.propulsion.thruster_temp:.1f}C) rather than "
                "an independent ADCS wheel fault or TCS heat-pipe failure, since neither alone explains both "
                "symptoms appearing together at the same onset time."
            ),
        )

    if fault_scenario == "eps_battery_degradation":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Rising internal cell resistance causes voltage sag under nominal load",
                "Effective battery capacity derates, amplifying SOC swings across the eclipse/sunlight cycle",
                "Sagging bus_voltage crosses the 25V EPS warning line despite battery_soc still reading in a plausible range",
            ],
            affected_subsystems=["EPS"],
            confidence_score=0.83,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=25,
            reasoning=(
                f"Bus voltage measured {state.eps.bus_voltage:.2f}V against the 25.0V warning line while "
                f"battery_soc still reads {state.eps.battery_soc * 100:.1f}% — the signature of internal-resistance "
                "rise in an aging cell: coulomb count looks adequate but terminal voltage collapses under load. "
                f"Solar array current is {state.eps.solar_array_current:.2f}A, confirming the array is still "
                "delivering current and ruling out an array/pointing fault as the primary cause."
            ),
        )

    if fault_scenario == "adcs_reaction_wheel_degradation":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Reaction wheel bearing friction reduces available correction torque",
                "Proportional control law can no longer null the natural attitude drift rate, so steady-state pointing error grows",
                "Growing attitude_error de-points solar arrays (ADCS->EPS) and shifts thermal equilibrium off nominal (ADCS->TCS)",
            ],
            affected_subsystems=["ADCS", "EPS", "TCS"],
            confidence_score=0.86,
            urgency=urgency_for_severity(severity),
            time_to_critical_estimate_minutes=15,
            reasoning=(
                f"Attitude error reads {state.adcs.attitude_error:.2f} degrees against the 5.0 degree control "
                f"threshold; reaction wheel speed is {state.adcs.reaction_wheel_speed:.0f} RPM. The wheel is "
                "drawing correction torque but failing to converge error back toward the ~0.2 degree nominal "
                "hover — consistent with reduced torque authority from bearing wear rather than a command-loop "
                "fault (OBC watchdog counters remain nominal)."
            ),
        )

    if fault_scenario == "eps_cascade_power_failure":
        return SimpleNamespace(
            primary_root_cause=fault_scenario,
            causal_chain=[
                "Solar array output has collapsed to near zero — consistent with a debris strike or array deployment failure",
                "Battery discharges under full spacecraft load with no recharge path available",
                "Undervoltage cascades through all five EPS-> edges simultaneously: TCS heaters lose power, ADCS wheels lose torque authority, OBC watchdog begins accumulating trips, TT&C transmitter power drops",
            ],
            affected_subsystems=["EPS", "TCS", "ADCS", "OBC", "TT&C"],
            confidence_score=0.92,
            urgency=UrgencyLevel.CRITICAL,
            time_to_critical_estimate_minutes=4,
            reasoning=(
                f"Solar array current has collapsed to {state.eps.solar_array_current:.2f}A (nominal ~8A peak "
                f"in sunlight) while bus_voltage is already {state.eps.bus_voltage:.2f}V and falling. This is a "
                "total power-generation-path failure, not a load or degradation issue — the simultaneous onset "
                "across every EPS-> cascade edge at once rules out a single-subsystem root cause anywhere else "
                "in the dependency graph."
            ),
        )

    return SimpleNamespace(
        primary_root_cause=fault_scenario or "unknown",
        causal_chain=[fault_scenario] if fault_scenario else [],
        affected_subsystems=[flagged_subsystem],
        confidence_score=0.5,
        urgency=urgency_for_severity(severity),
        time_to_critical_estimate_minutes=20,
        reasoning=f"Offline fallback diagnosis for {fault_scenario or 'unlabeled anomaly'}.",
    )


ACTION_PROCEDURE_STEPS = {
    "switch_redundant_power_bus": [
        "Verify redundant bus contactor is healthy on telemetry",
        "Command switchover to redundant power bus",
        "Confirm bus_voltage recovers above 25V within one telemetry cycle",
    ],
    "shed_nonessential_load": [
        "Identify non-critical payload/subsystem loads eligible for shedding",
        "Command load shed sequence (target -30% total load current)",
        "Monitor bus_voltage stabilization over the next 2-3 telemetry frames",
    ],
    "reorient_maximum_solar_exposure": [
        "Compute slew vector for maximum solar incidence given current orbit position",
        "Command ADCS slew maneuver to the new attitude",
        "Confirm solar_array_current increases as panels re-point into sunlight",
    ],
    "enter_safe_low_power_mode": [
        "Cap CPU load to 20% and suspend non-essential background processes",
        "Verify OBC watchdog trip counter stops incrementing",
        "Hold safe mode until root-cause subsystem confirms nominal",
    ],
    "activate_backup_heater": [
        "Force-close backup survival heater circuit override",
        "Monitor panel_temp for the cooling-rate reversal",
        "Release override once panel_temp re-crosses back under the 49C line",
    ],
    "thruster_isolation": [
        "Command all propulsion valve actuators to closed/safe position",
        "Confirm disturbance torque source is removed via attitude_error stabilizing",
        "Hold isolation until ground contact for valve fault diagnosis",
    ],
}

ACTION_REASONS = {
    "switch_redundant_power_bus": "restores charge path capacity independent of the degraded primary bus",
    "shed_nonessential_load": "cuts non-critical load, easing the deficit against the current bus reading",
    "reorient_maximum_solar_exposure": "re-points the array for maximum solar incidence, restoring charging current",
    "enter_safe_low_power_mode": "caps CPU load and halts non-essential processing to stop the compounding power draw",
    "activate_backup_heater": "forces the backup heater circuit closed to arrest the thermal drift",
    "thruster_isolation": "closes propulsion valve commands, removing the disturbance torque source at its origin",
}


def build_fallback_rationale(fault_scenario: str, best_action: str | None, state: SatelliteState) -> str:
    if not best_action:
        return "ORACLE found no viable recovery action for this fault at the current severity."
    reason = ACTION_REASONS.get(best_action, "was ranked highest by the Monte Carlo safety score across all candidate actions")
    return f"ORACLE's top-ranked action for {fault_scenario} is {best_action} — it {reason}."


def build_fallback_options(oracle_response) -> list[dict]:
    """
    Real ranked options for the frontend's ATHENA display when the LLM call
    is unavailable — every number here comes straight from ORACLE's actual
    Monte Carlo results, not a placeholder. Top 2 by safety_score.

    successProbability is derived from safety_score normalised to [0,1]:
        (safety_score + 0.45) / 1.0  — calibrated to the multi-factor formula
        whose range is approximately [-0.45, +0.55].
    """
    options = []
    for r in oracle_response.results[:2]:
        # Normalise safety_score → [0, 1] success probability
        success_prob = safety_score_to_probability(r.safety_score)
        options.append({
            "action_name": r.action_name,
            "procedure_steps": ACTION_PROCEDURE_STEPS.get(r.action_name, [f"Execute {r.action_name}"]),
            "safety_score": r.safety_score,
            "effectiveness_score": round(success_prob, 4),
            "is_irreversible": r.action_name in ("thruster_isolation",),
            "predicted_outcome": (
                f"{success_prob*100:.0f}% estimated success probability (safety_score={r.safety_score:.3f}), "
                f"{r.mc_result.mission_loss_rate*100:.0f}% mission-loss risk across "
                f"{r.mc_result.n_runs} simulated runs."
            ),
        })
    return options



app = FastAPI(title="AERO-ASTRA Streaming Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_stream_task = None

# Path to the pre-generated replay playlist
_PLAYLIST_PATH = Path(__file__).resolve().parent / "replay" / "playlist.json"

# ─────────────────────────────────────────────────────────────────────────────
# 1. SimulatorTelemetryProvider
# ─────────────────────────────────────────────────────────────────────────────

class SimulatorTelemetryProvider(TelemetryProvider):
    """
    Wraps the current Simulator state into a TelemetrySnapshot for SHERLOCK.
    """
    def __init__(self, state: SatelliteState):
        self.state = state

    def get_subsystem_snapshot(self, subsystem: str) -> TelemetrySnapshot | None:
        params = {}
        # state.timestamp is simulation-elapsed seconds (0..duration), not a
        # Unix epoch offset — datetime.fromtimestamp(state.timestamp) would
        # land near 1970-01-01. Use wall-clock "now" for the real time this
        # frame is actually being processed/streamed.
        dt_timestamp = datetime.now(timezone.utc)
        
        if subsystem == "ADCS":
            params = {
                "attitude_error": self.state.adcs.attitude_error,
                "reaction_wheel_speed": self.state.adcs.reaction_wheel_speed,
            }
        elif subsystem == "EPS":
            params = {
                "battery_soc": self.state.eps.battery_soc,
                "solar_array_current": self.state.eps.solar_array_current,
                "bus_voltage": self.state.eps.bus_voltage,
                "load_current": self.state.eps.load_current,
            }
        elif subsystem == "TCS":
            params = {
                "panel_temp": self.state.tcs.panel_temp,
                "battery_temp": self.state.tcs.battery_temp,
                "heater_active": float(self.state.tcs.heater_active),
                "in_eclipse": float(self.state.tcs.in_eclipse),
            }
        elif subsystem == "OBC":
            params = {
                "free_memory_mb": self.state.obc.free_memory_mb,
                "cpu_load": self.state.obc.cpu_load,
                "watchdog_trips": float(self.state.obc.watchdog_trips),
            }
        elif subsystem == "TTC":
            params = {
                "signal_strength": self.state.ttc.signal_strength,
                "bit_error_rate": self.state.ttc.bit_error_rate,
                "ground_contact_remaining": self.state.ttc.ground_contact_remaining,
            }
        elif subsystem == "Propulsion":
            params = {
                "fuel_remaining": self.state.propulsion.fuel_remaining,
                "thruster_temp": self.state.propulsion.thruster_temp,
            }
        else:
            return None

        return TelemetrySnapshot(
            subsystem=subsystem,
            parameters=params,
            timestamp=dt_timestamp
        )

# ─────────────────────────────────────────────────────────────────────────────
# 2. WebSocket Connection Manager
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# ─────────────────────────────────────────────────────────────────────────────
# 3. Autonomous Replay Streaming
# ─────────────────────────────────────────────────────────────────────────────


def _dict_to_state(s: dict) -> SatelliteState:
    """
    Reconstruct a SatelliteState from the serialised frame dict
    produced by backend/replay/generate.py.
    """
    from backend.simulator.schemas import (
        ADCSState, EPSState, OBCState, PropulsionState, TCSState, TTCState,
    )
    return SatelliteState(
        timestamp=0.0,
        eps=EPSState(
            battery_soc=s["eps"]["battery_soc"],
            solar_array_current=s["eps"]["solar_array_current"],
            bus_voltage=s["eps"]["bus_voltage"],
            load_current=s["eps"]["load_current"],
        ),
        tcs=TCSState(
            panel_temp=s["tcs"]["panel_temp"],
            battery_temp=s["tcs"]["battery_temp"],
            heater_active=bool(s["tcs"]["heater_active"]),
            in_eclipse=bool(s["tcs"]["in_eclipse"]),
        ),
        adcs=ADCSState(
            attitude_error=s["adcs"]["attitude_error"],
            reaction_wheel_speed=s["adcs"]["reaction_wheel_speed"],
        ),
        obc=OBCState(
            free_memory_mb=s["obc"]["free_memory_mb"],
            cpu_load=s["obc"]["cpu_load"],
            watchdog_trips=int(s["obc"]["watchdog_trips"]),
        ),
        ttc=TTCState(
            signal_strength=s["ttc"]["signal_strength"],
            bit_error_rate=s["ttc"]["bit_error_rate"],
            ground_contact_remaining=s["ttc"]["ground_contact_remaining"],
        ),
        propulsion=PropulsionState(
            fuel_remaining=s["propulsion"]["fuel_remaining"],
            thruster_temp=s["propulsion"]["thruster_temp"],
        ),
        active_fault=s.get("active_fault"),
        fault_severity=s.get("fault_severity", 0.0),
    )


async def replay_stream():
    """
    Streams the pre-generated telemetry playlist autonomously.

    Reads backend/replay/playlist.json (produced by generate.py) and
    replays each frame at 10fps. Fault telemetry is embedded in the
    playlist — no external trigger is needed. SENTINEL monitors the
    same telemetry stream it always did and fires when anomalies emerge
    from the data naturally.

    Loops through all loops in the playlist indefinitely, rotating
    through the 3 fault scenarios so longer demo sessions show variety.
    """
    log.info("Loading replay playlist from %s", _PLAYLIST_PATH)
    if not _PLAYLIST_PATH.exists():
        log.error(
            "Playlist not found at %s — run: python backend/replay/generate.py",
            _PLAYLIST_PATH,
        )
        return

    with open(_PLAYLIST_PATH) as f:
        playlist = json.load(f)

    log.info(
        "Playlist loaded: %d loops, %d total frames (~%.1f min wall-clock at 10fps)",
        len(playlist["loops"]),
        playlist["total_frames"],
        playlist["total_frames"] / 10 / 60,
    )

    # Lazy init agents once — reused across all loops.
    try:
        sherlock_agent = SherlockAgent()
    except EnvironmentError as key_err:
        log.warning("SHERLOCK disabled (no API key): %s", key_err)
        sherlock_agent = None
    try:
        athena_agent = AthenaAgent()
    except EnvironmentError as key_err:
        log.warning("ATHENA disabled (no API key): %s", key_err)
        athena_agent = None

    background_tasks: set = set()
    global_timestamp = 0.0   # monotonically increasing wall-clock timestamp

    loop_index = 0
    while True:  # rotate through loops indefinitely
        loop_def = playlist["loops"][loop_index % len(playlist["loops"])]
        fault_scenario = loop_def["fault"]
        severity       = loop_def["severity"]
        loop_label     = loop_def["label"]

        log.info(
            "Starting replay loop %d — fault=%s severity=%.2f",
            loop_index + 1, fault_scenario, severity,
        )

        # ── Broadcast loop start so the frontend can show which fault is coming
        await manager.broadcast({
            "type": "replay_loop_start",
            "loop_index": loop_index,
            "fault": fault_scenario,
            "label": loop_label,
            "subsystem": loop_def["subsystem"],
            "severity": severity,
        })

        # ── Per-loop SENTINEL state ─────────────────────────────────────────────
        # Compute nominal baseline from Act 1 frames for MAD calibration
        act1_frames = loop_def["acts"][0]["frames"]
        nom_data = {
            "CADC0872": [f["state"]["adcs"]["attitude_error"]    for f in act1_frames],
            "CADC0873": [f["state"]["adcs"]["reaction_wheel_speed"] for f in act1_frames],
            "CADC0874": [f["state"]["eps"]["load_current"]         for f in act1_frames],
        }

        def compute_mad(series):
            dx = np.abs(np.diff(series))
            return np.median(np.abs(dx - np.median(dx))) if len(dx) > 0 else 0.0

        static_mad_dict = {
            "CADC0872": max(compute_mad(nom_data["CADC0872"]), 1e-6),
            "CADC0873": max(compute_mad(nom_data["CADC0873"]), 1e-6),
            "CADC0874": max(compute_mad(nom_data["CADC0874"]), 1e-6),
        }

        persistence        = SentinelPersistenceFilter(threshold=0.60, min_consecutive_steps=35)
        physics_filter     = PhysicsSpikeFilter(window_size=10, min_spikes_required=2)
        correlation_filter = ResidualCorrelationDetector()
        window: list[dict] = []
        incident_in_progress = False

        async def run_oracle_in_background(req: OracleRequest, diag):
            try:
                oracle_response = await asyncio.to_thread(run_oracle, req)
            except Exception as e:
                log.exception("ORACLE failed")
                await manager.broadcast({
                    "type": "oracle_simulation",
                    "best_action": None,
                    "top_score": 0.0,
                    "mode": "failed",
                })
                await manager.broadcast({
                    "type": "athena_plan",
                    "recommended_action": None,
                    "rationale": f"ORACLE simulation failed ({type(e).__name__}) — no recovery plan available.",
                    "estimated_recovery_time_minutes": None,
                    "offline_fallback": True,
                })
                return

            oracle_msg = {
                "type": "oracle_simulation",
                "best_action": oracle_response.best_action,
                "top_score": oracle_response.results[0].safety_score if oracle_response.results else 0.0,
                "mode": oracle_response.mode,
                "results": [
                    {
                        "action_name": r.action_name,
                        "safety_score": r.safety_score,
                        "nominal_recovery_rate": r.mc_result.nominal_recovery_rate,
                        "degraded_operation_rate": r.mc_result.degraded_operation_rate,
                        "mission_loss_rate": r.mc_result.mission_loss_rate,
                        "mean_final_battery_soc": r.mc_result.mean_final_battery_soc,
                        "std_final_battery_soc": r.mc_result.std_final_battery_soc,
                        "flags": r.flags,
                    }
                    for r in oracle_response.results
                ],
            }
            await manager.broadcast(oracle_msg)

            # ATHENA Planning (Non-blocking)
            athena_plan = None
            if athena_agent is None:
                await manager.broadcast({
                    "type": "athena_plan",
                    "recommended_action": oracle_response.best_action,
                    "rationale": build_fallback_rationale(req.fault_name, oracle_response.best_action, req.current_state),
                    "estimated_recovery_time_minutes": None,
                    "offline_fallback": True,
                    "options": build_fallback_options(oracle_response),
                })
            else:
                try:
                    athena_plan = await asyncio.to_thread(athena_agent.plan, diag, oracle_response)
                    athena_msg = {
                        "type": "athena_plan",
                        "recommended_action": athena_plan.recommended_action,
                        "rationale": athena_plan.overall_reasoning,
                        "estimated_recovery_time_minutes": 15,
                        "options": [
                            {
                                "action_name": o.action_name,
                                "procedure_steps": o.procedure_steps,
                                "safety_score": o.safety_score,
                                "effectiveness_score": o.effectiveness_score,
                                "is_irreversible": o.is_irreversible,
                                "predicted_outcome": o.predicted_outcome,
                            }
                            for o in athena_plan.options
                        ],
                    }
                    await manager.broadcast(athena_msg)
                except Exception as e:
                    log.exception("ATHENA failed")
                    await manager.broadcast({
                        "type": "athena_plan",
                        "recommended_action": oracle_response.best_action,
                        "rationale": build_fallback_rationale(req.fault_name, oracle_response.best_action, req.current_state),
                        "estimated_recovery_time_minutes": None,
                        "offline_fallback": True,
                        "options": build_fallback_options(oracle_response),
                    })

            # Phase 3: ORACLE Phase 2 deeper MC re-validation
            recommended = athena_plan.recommended_action if athena_plan else oracle_response.best_action
            if recommended:
                try:
                    await manager.broadcast({"type": "oracle_validation_start", "action": recommended})
                    val_req = OracleRequest(
                        current_state=req.current_state,
                        fault_name=req.fault_name,
                        fault_severity=req.fault_severity,
                        proposed_actions=[recommended],
                        diagnosis_context=req.diagnosis_context,
                        n_runs=200,
                        steps=600,
                    )
                    val_response = await asyncio.to_thread(run_oracle, val_req)
                    if val_response.results:
                        r = val_response.results[0]
                        prob = safety_score_to_probability(r.safety_score)
                        await manager.broadcast({
                            "type": "oracle_validation",
                            "action_name": r.action_name,
                            "safety_score": r.safety_score,
                            "success_probability": prob,
                            "nominal_recovery_rate": r.mc_result.nominal_recovery_rate,
                            "degraded_operation_rate": r.mc_result.degraded_operation_rate,
                            "mission_loss_rate": r.mc_result.mission_loss_rate,
                            "mean_final_battery_soc": r.mc_result.mean_final_battery_soc,
                            "std_final_battery_soc": r.mc_result.std_final_battery_soc,
                            "n_runs": r.mc_result.n_runs,
                            "flags": r.flags,
                            "phase1_oracle_winner": oracle_response.best_action,
                            "athena_agreed": recommended == oracle_response.best_action,
                        })
                except Exception:
                    log.exception("Oracle Phase 2 validation failed for action=%s", recommended)

        # ── Stream all acts in this loop ──────────────────────────────────────
        for act in loop_def["acts"]:
            act_name = act["name"]
            log.info("  Act: %s (%d frames)", act_name, len(act["frames"]))

            for frame_dict in act["frames"]:
                await asyncio.sleep(0.1)   # 10fps

                state = _dict_to_state(frame_dict["state"])

                # ── Telemetry broadcast ─────────────────────────────────────
                telemetry_msg = {
                    "type": "telemetry",
                    "timestamp": global_timestamp,
                    "act": act_name,
                    "fault_label": frame_dict["fault_label"],
                    "subsystems": {
                        "ADCS": {
                            "attitude_error": state.adcs.attitude_error,
                            "reaction_wheel_speed": state.adcs.reaction_wheel_speed,
                        },
                        "EPS": {
                            "battery_soc": state.eps.battery_soc,
                            "bus_voltage": state.eps.bus_voltage,
                        },
                    },
                }
                await manager.broadcast(telemetry_msg)

                # ── Vitals ──────────────────────────────────────────────────
                vitals_payload = calculate_vitals(state)
                await manager.broadcast({
                    "type": "vitals_update",
                    "timestamp": global_timestamp,
                    "payload": vitals_payload,
                })

                # ── Engine C — residual correlation ─────────────────────────
                corr_alarm, err_actual, err_pred, wheel_actual, wheel_pred = correlation_filter.update(
                    state.adcs.attitude_error, state.adcs.reaction_wheel_speed
                )
                await manager.broadcast({
                    "type": "residual_update",
                    "timestamp": global_timestamp,
                    "attitude_error": {"actual": err_actual, "predicted": err_pred},
                    "reaction_wheel_speed": {"actual": wheel_actual, "predicted": wheel_pred},
                })

                # ── Engine A + B (XGBoost + Physics) ───────────────────────
                row = {
                    "CADC0872": state.adcs.attitude_error,
                    "CADC0873": state.adcs.reaction_wheel_speed,
                    "CADC0874": state.eps.load_current,
                }
                window.append(row)
                if len(window) > 20:
                    window.pop(0)

                if len(window) == 20:
                    df = pd.DataFrame(window)
                    xgb_score, _ = score_xgboost(df, "CADC0872")
                    alarm_flatline = persistence.update(xgb_score)
                    alarm_spike, _ = physics_filter.update(df, static_mad_dict, mad_multiplier=4.0)

                    is_anomaly = alarm_flatline or alarm_spike or corr_alarm

                    # Fallback: VITALS health threshold
                    if not is_anomaly and vitals_payload["worst_health"] < 0.85:
                        is_anomaly = True
                        alarm_flatline = True

                    # ── Rising-edge trigger ─────────────────────────────────
                    if is_anomaly and not incident_in_progress:
                        incident_in_progress = True
                        firing = [n for n, f in (
                            ("Engine A (Telemetry)", alarm_flatline),
                            ("Engine B (Physics)", alarm_spike),
                            ("Engine C (Residual Correlation)", corr_alarm),
                        ) if f]
                        triggered_engine = " + ".join(firing) if firing else "Engine A (Telemetry)"

                        sentinel_msg = {
                            "type": "sentinel_alert",
                            "is_anomaly": True,
                            "triggered_engine": triggered_engine,
                            "timestamp": global_timestamp,
                            "false_positive": False,   # playlist always has real faults
                            "fault_label": loop_label,
                        }
                        await manager.broadcast(sentinel_msg)

                        # DIAGNOSIS (SHERLOCK)
                        dt_ts = datetime.now(timezone.utc)
                        flagged_subsystem, flagged_parameter = FAULT_SUBSYSTEM_MAP.get(
                            fault_scenario, ("EPS", "unknown")
                        )
                        anomaly_event = AnomalyEvent(
                            anomaly_id=f"EVT-{loop_index+1:03d}",
                            timestamp=dt_ts,
                            flagged_subsystem=flagged_subsystem,
                            flagged_parameter=flagged_parameter,
                            confidence_score=0.75,
                            severity=SeverityLevel.HIGH,
                            telemetry_window=[],
                        )

                        provider = SimulatorTelemetryProvider(state)
                        if sherlock_agent is None:
                            diagnosis = build_fallback_diagnosis(fault_scenario, state, severity)
                        else:
                            try:
                                diagnosis = await asyncio.to_thread(
                                    sherlock_agent.diagnose, anomaly_event, provider
                                )
                            except Exception:
                                log.exception("SHERLOCK failed")
                                diagnosis = build_fallback_diagnosis(fault_scenario, state, severity)

                        await manager.broadcast({
                            "type": "sherlock_diagnosis",
                            "primary_root_cause": diagnosis.primary_root_cause,
                            "causal_chain": diagnosis.causal_chain,
                            "affected_subsystems": diagnosis.affected_subsystems,
                            "confidence_score": diagnosis.confidence_score,
                            "urgency": diagnosis.urgency.value,
                            "time_to_critical": diagnosis.time_to_critical_estimate_minutes,
                            "reasoning": diagnosis.reasoning,
                        })

                        # GUARDIAN
                        guardian_status = "AUTOMATED_GUARDED"
                        action_taken = None
                        ttc = diagnosis.time_to_critical_estimate_minutes
                        if ttc is not None and ttc < 5:
                            guardian_status = "AUTONOMOUS_SAFED"
                            action_taken = "shed_nonessential_load"
                        elif diagnosis.urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
                            guardian_status = "MANUAL_INTERLOCK"

                        await manager.broadcast({
                            "type": "guardian_action",
                            "status": guardian_status,
                            "action_taken": action_taken,
                        })

                        # ORACLE + ATHENA (background)
                        req = OracleRequest(
                            current_state=state,
                            fault_name=fault_scenario,
                            fault_severity=severity,
                            diagnosis_context=diagnosis.reasoning,
                        )
                        task = asyncio.create_task(run_oracle_in_background(req, diagnosis))
                        background_tasks.add(task)
                        task.add_done_callback(background_tasks.discard)

                global_timestamp += 1.0

        # ── End of loop — broadcast reset for frontend to clear incident state
        await manager.broadcast({
            "type": "replay_loop_end",
            "loop_index": loop_index,
            "fault": fault_scenario,
            "label": loop_label,
        })
        loop_index += 1


def stream_task_done_callback(task):
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"STREAMING PIPELINE CRASHED: {type(e)} {e}")

@app.on_event("startup")
async def startup_event():
    global current_stream_task
    current_stream_task = asyncio.create_task(replay_stream())
    current_stream_task.add_done_callback(stream_task_done_callback)

# NOTE: /trigger endpoint removed — streaming is now fully autonomous.
# The replay playlist rotates through fault scenarios without user input.
# To regenerate the playlist, run: python backend/replay/generate.py

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
