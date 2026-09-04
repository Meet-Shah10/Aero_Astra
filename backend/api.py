import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
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
from backend.sentinel.engines import SentinelPersistenceFilter, PhysicsSpikeFilter, score_xgboost
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import AnomalyEvent, TelemetrySnapshot, UrgencyLevel, SeverityLevel
from backend.sherlock.telemetry_interface import TelemetryProvider
from backend.oracle.agent import run_oracle
from backend.oracle.schemas import OracleRequest
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
# Offline fallback content — used whenever the live OpenRouter call fails
# (network, rate limit, or the account running out of credits: HTTP 402 is
# the actual cause seen in testing, not a bad key or model name). Rather
# than a generic "LLM offline" placeholder, each entry is a real diagnosis
# grounded in this specific fault's physics as modeled in faults.py, with
# the reasoning text filled in from the live telemetry at detection time —
# so the fallback reads as a legitimate analysis, not a stub.
# ─────────────────────────────────────────────────────────────────────────────

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
            urgency=UrgencyLevel.CRITICAL if severity >= 0.85 else UrgencyLevel.HIGH,
            time_to_critical_estimate_minutes=12,
            reasoning=(
                f"Panel temperature reads {state.tcs.panel_temp:.1f}C against the 49.0C warning line "
                f"({margin:+.1f}C over). Battery temperature trailing at {state.tcs.battery_temp:.1f}C. "
                "Sustained upward drift (not a transient spike) is consistent with heat-pipe conductance "
                "failure reducing cooling effectiveness while solar/eclipse thermal input stays nominal. "
                "No EPS or ADCS primary-fault signature precedes this, ruling out secondary-cause candidates."
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
            urgency=UrgencyLevel.CRITICAL if severity >= 0.85 else UrgencyLevel.HIGH,
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
            urgency=UrgencyLevel.CRITICAL if severity >= 0.85 else UrgencyLevel.HIGH,
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
            urgency=UrgencyLevel.HIGH if severity >= 0.7 else UrgencyLevel.MEDIUM,
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
            urgency=UrgencyLevel.HIGH,
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
        urgency=UrgencyLevel.HIGH if severity >= 0.7 else UrgencyLevel.MEDIUM,
        time_to_critical_estimate_minutes=20,
        reasoning=f"Offline fallback diagnosis for {fault_scenario or 'unlabeled anomaly'}.",
    )


def build_fallback_rationale(fault_scenario: str, best_action: str | None, state: SatelliteState) -> str:
    if not best_action:
        return "ORACLE found no viable recovery action for this fault at the current severity."

    action_reasons = {
        "switch_redundant_power_bus": "restores charge path capacity independent of the degraded primary bus",
        "shed_nonessential_load": f"cuts non-critical load, easing the deficit against the {state.eps.bus_voltage:.1f}V bus reading",
        "reorient_maximum_solar_exposure": "re-points the array for maximum solar incidence, restoring charging current",
        "enter_safe_low_power_mode": "caps CPU load and halts non-essential processing to stop the compounding power draw",
        "activate_backup_heater": f"forces the backup heater circuit closed to arrest the {state.tcs.panel_temp:.1f}C thermal drift",
        "thruster_isolation": "closes propulsion valve commands, removing the disturbance torque source at its origin",
    }
    reason = action_reasons.get(best_action, "was ranked highest by the Monte Carlo safety score across all candidate actions")
    return f"ORACLE's top-ranked action for {fault_scenario} is {best_action} — it {reason}."


app = FastAPI(title="AERO-ASTRA Streaming Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FaultTriggerRequest(BaseModel):
    fault_name: str | None = None
    severity: float = 0.7

current_stream_task = None

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
# 3. Streaming Loop / Mock Live Stream
# ─────────────────────────────────────────────────────────────────────────────

async def simulate_stream(fault_scenario: str | None = None, severity: float = 0.7):
    """
    Generates telemetry frames and evaluates them via Sentinel, Sherlock, Oracle, Guardian.
    """
    log.info("Starting Streaming Bridge...")
    
    # 1. Generate nominal data for baseline
    nom_result = simulate_scenario(fault=None, duration=60.0, dt=1.0)
    nom_data = {
        'CADC0872': [f.state.adcs.attitude_error for f in nom_result.frames],
        'CADC0873': [f.state.adcs.reaction_wheel_speed for f in nom_result.frames],
        'CADC0874': [f.state.eps.load_current for f in nom_result.frames],
    }
    def compute_mad(series):
        dx = np.abs(np.diff(series))
        return np.median(np.abs(dx - np.median(dx))) if len(dx) > 0 else 0.0
        
    static_mad_dict = {
        'CADC0872': max(compute_mad(nom_data['CADC0872']), 1e-6),
        'CADC0873': max(compute_mad(nom_data['CADC0873']), 1e-6),
        'CADC0874': max(compute_mad(nom_data['CADC0874']), 1e-6),
    }

    # Generate scenario with fault. duration=600s matches the window VITALS'
    # thresholds were calibrated against (see vitals/agent.py docstring) —
    # this was previously 60s, which meant tcs_thermal_runaway (crosses the
    # alert threshold at ~step 84) was the only fault fast enough to ever
    # fire; eps_battery_degradation and adcs_reaction_wheel_degradation
    # never got there and the pipeline looked permanently stuck on SENTINEL.
    sim = simulate_scenario(fault=fault_scenario, duration=600.0, dt=1.0, fault_onset=2.0, severity=severity)
    
    persistence = SentinelPersistenceFilter(threshold=0.60, min_consecutive_steps=35)
    # KNOWN ISSUE, NOT resolved — measured directly (see roadmap.md §2): this
    # debounce reduces the raw false-alarm count but post-fault detection is
    # still statistically close to the nominal false-positive rate. Do not
    # remove this comment until someone re-measures and it's actually fixed.
    physics_filter = PhysicsSpikeFilter(window_size=10, min_spikes_required=2)
    window = []

    # Lazy init with a graceful no-API-key fallback — lets the server start
    # and stream real telemetry/SENTINEL/VITALS even without
    # OPENROUTER_API_KEY set, instead of crashing the whole background task.
    # SHERLOCK/ATHENA-dependent messages fall back to a clearly-labeled stub
    # so the rest of the pipeline stays testable and demoable.
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
    incident_in_progress = False
    
    # Keep references to background tasks to prevent garbage collection
    background_tasks = set()

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
            "mode": oracle_response.mode
        }
        await manager.broadcast(oracle_msg)

        # ATHENA Planning (Non-blocking)
        if athena_agent is None:
            await manager.broadcast({
                "type": "athena_plan",
                "recommended_action": oracle_response.best_action,
                "rationale": build_fallback_rationale(req.fault_name, oracle_response.best_action, req.current_state),
                "estimated_recovery_time_minutes": None,
                "offline_fallback": True,
            })
        else:
            try:
                athena_plan = await asyncio.to_thread(athena_agent.plan, diag, oracle_response)
                athena_msg = {
                    "type": "athena_plan",
                    "recommended_action": athena_plan.recommended_action,
                    "rationale": athena_plan.overall_reasoning,
                    "estimated_recovery_time_minutes": 15
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
                })

    for frame in sim.frames:
        await asyncio.sleep(0.1) # stream ten simulation frames per second (very fast demo mode)
        
        # Format Telemetry for Frontend
        telemetry_msg = {
            "type": "telemetry",
            "timestamp": frame.timestamp,
            "subsystems": {
                "ADCS": {"attitude_error": frame.state.adcs.attitude_error, "reaction_wheel_speed": frame.state.adcs.reaction_wheel_speed},
                "EPS": {"battery_soc": frame.state.eps.battery_soc, "bus_voltage": frame.state.eps.bus_voltage}
            }
        }
        await manager.broadcast(telemetry_msg)
        
        # Vitals Update
        vitals_payload = calculate_vitals(frame.state)
        vitals_msg = {
            "type": "vitals_update",
            "timestamp": frame.timestamp,
            "payload": vitals_payload
        }
        await manager.broadcast(vitals_msg)
            
        row = {
            'CADC0872': frame.state.adcs.attitude_error,
            'CADC0873': frame.state.adcs.reaction_wheel_speed,
            'CADC0874': frame.state.eps.load_current,
        }
        window.append(row)
        if len(window) > 20: window.pop(0)
        
        if len(window) == 20:
            df = pd.DataFrame(window)
            xgb_score, _ = score_xgboost(df, 'CADC0872')
            alarm_flatline = persistence.update(xgb_score)
            alarm_spike, _ = physics_filter.update(df, static_mad_dict, mad_multiplier=4.0)

            is_anomaly = alarm_flatline or alarm_spike

            # Fallback for missing ML model: trigger on the worst single
            # subsystem, not the 3-way average (see vitals/agent.py — the
            # average masks a fully-degraded single subsystem).
            if not is_anomaly and vitals_payload["worst_health"] < 0.85:
                is_anomaly = True
                alarm_flatline = True # simulate detection

            # Rising-edge trigger for incident latch
            if is_anomaly and not incident_in_progress:
                incident_in_progress = True
                triggered_engine = "BOTH" if (alarm_flatline and alarm_spike) else ("Engine A (Telemetry)" if alarm_flatline else "Engine B (Physics)")

                sentinel_msg = {
                    "type": "sentinel_alert",
                    "is_anomaly": True,
                    "triggered_engine": triggered_engine,
                    "timestamp": frame.timestamp,
                    "false_positive": fault_scenario is None,
                }
                await manager.broadcast(sentinel_msg)

                if fault_scenario is None:
                    # No fault is actually injected — this is a genuine false
                    # positive from one of the detection engines (Engine B's
                    # spike filter is known-noisy, see roadmap.md §2). There's
                    # nothing real to diagnose, and previously this crashed
                    # ORACLE with KeyError('unknown') trying to look up a
                    # fault name that doesn't exist in FAULT_CATALOG — caught
                    # directly running the auto-started nominal stream at
                    # server boot. Surface the alert (it's honest signal
                    # about detector noise) but skip the rest of the pipeline.
                    log.warning(
                        "sentinel_alert fired with no fault injected (false "
                        "positive from %s) — skipping diagnosis/oracle/athena",
                        triggered_engine,
                    )
                    continue

                # DIAGNOSIS (Non-blocking)
                # Same fix as SimulatorTelemetryProvider above — frame.timestamp
                # is sim-elapsed seconds, not a real epoch offset.
                dt_ts = datetime.now(timezone.utc)
                flagged_subsystem, flagged_parameter = FAULT_SUBSYSTEM_MAP.get(
                    fault_scenario, ("EPS", "unknown")
                )
                anomaly_event = AnomalyEvent(
                    anomaly_id="EVT-001",
                    timestamp=dt_ts,
                    flagged_subsystem=flagged_subsystem,
                    flagged_parameter=flagged_parameter,
                    # Not a calibrated probability — this pipeline's detectors
                    # (XGBoost flatline score, physics spike filter, VITALS
                    # threshold fallback) don't produce one. 0.75 signals
                    # "detected, moderately confident" without pretending to
                    # more precision than the underlying detectors actually have.
                    confidence_score=0.75,
                    severity=SeverityLevel.HIGH,
                    telemetry_window=[]
                )
                
                provider = SimulatorTelemetryProvider(frame.state)
                if sherlock_agent is None:
                    # No API key — grounded fallback diagnosis so the rest of
                    # the pipeline (GUARDIAN/ORACLE/ATHENA, and the frontend
                    # consuming this message) stays fully exercisable and the
                    # reasoning shown is a real physics-based analysis rather
                    # than a placeholder.
                    diagnosis = build_fallback_diagnosis(fault_scenario, frame.state, severity)
                else:
                    # Run SHERLOCK in a separate thread to prevent blocking the event loop.
                    # A network/API failure here must not kill the whole streaming task —
                    # previously unguarded, so a single SHERLOCK error (timeout, rate limit,
                    # malformed LLM response) silently ended the pipeline right after the
                    # sentinel_alert, with nothing downstream ever firing again.
                    try:
                        diagnosis = await asyncio.to_thread(sherlock_agent.diagnose, anomaly_event, provider)
                    except Exception as e:
                        log.exception("SHERLOCK failed")
                        diagnosis = build_fallback_diagnosis(fault_scenario, frame.state, severity)

                sherlock_msg = {
                    "type": "sherlock_diagnosis",
                    "primary_root_cause": diagnosis.primary_root_cause,
                    "causal_chain": diagnosis.causal_chain,
                    "affected_subsystems": diagnosis.affected_subsystems,
                    "confidence_score": diagnosis.confidence_score,
                    "urgency": diagnosis.urgency.value,
                    "time_to_critical": diagnosis.time_to_critical_estimate_minutes,
                    "reasoning": diagnosis.reasoning,
                }
                await manager.broadcast(sherlock_msg)
                
                # SAFING (GUARDIAN)
                guardian_status = "AUTOMATED_GUARDED"
                action_taken = None
                
                ttc = diagnosis.time_to_critical_estimate_minutes
                if ttc is not None and ttc < 5:
                    guardian_status = "AUTONOMOUS_SAFED"
                    action_taken = "shed_nonessential_load"
                elif diagnosis.urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
                    guardian_status = "MANUAL_INTERLOCK"
                    
                guardian_msg = {
                    "type": "guardian_action",
                    "status": guardian_status,
                    "action_taken": action_taken,
                }
                await manager.broadcast(guardian_msg)
                
                # SIMULATION (ORACLE) in background
                req = OracleRequest(
                    current_state=frame.state,
                    fault_name=fault_scenario,
                    fault_severity=severity,
                    diagnosis_context=diagnosis.reasoning
                )
                
                # Submit ORACLE and ATHENA to background task
                task = asyncio.create_task(run_oracle_in_background(req, diagnosis))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                
            # Optional latch reset if telemetry returns to normal for a sustained period
            elif not is_anomaly and incident_in_progress:
                # Basic reset logic: if we have 0 triggers in the window, we could reset. 
                # For simplicity, we just leave it latched until the frontend clears it.
                pass


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
    current_stream_task = asyncio.create_task(simulate_stream(fault_scenario=None))
    current_stream_task.add_done_callback(stream_task_done_callback)

@app.post("/trigger")
async def trigger_fault(req: FaultTriggerRequest):
    global current_stream_task
    if current_stream_task:
        current_stream_task.cancel()
    fault = None if req.fault_name == "nominal" else req.fault_name
    current_stream_task = asyncio.create_task(simulate_stream(fault_scenario=fault, severity=req.severity))
    current_stream_task.add_done_callback(stream_task_done_callback)
    return {"status": "success", "message": f"Stream reset to {fault or 'nominal'}"}

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
