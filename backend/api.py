import asyncio
import json
import logging
from datetime import datetime, timezone
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
from backend.sherlock.schemas import AnomalyEvent, TelemetrySnapshot, UrgencyLevel
from backend.sherlock.telemetry_interface import TelemetryProvider
from backend.oracle.agent import run_oracle
from backend.oracle.schemas import OracleRequest
from backend.athena.agent import AthenaAgent
from backend.vitals.agent import calculate_vitals
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

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
    nom_result = simulate_scenario(fault=None, duration=600.0, dt=1.0)
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

    # Generate scenario with fault
    sim = simulate_scenario(fault=fault_scenario, duration=600.0, dt=1.0, fault_onset=5.0, severity=severity)
    
    persistence = SentinelPersistenceFilter(threshold=0.60, min_consecutive_steps=35)
    # KNOWN ISSUE [RESOLVED] — PhysicsSpikeFilter now implements a rolling event-count debounce
    physics_filter = PhysicsSpikeFilter(window_size=10, min_spikes_required=2)
    window = []
    
    sherlock_agent = SherlockAgent()
    athena_agent = AthenaAgent()
    incident_in_progress = False
    
    # Keep references to background tasks to prevent garbage collection
    background_tasks = set()

    async def run_oracle_in_background(req: OracleRequest, diag):
        oracle_response = await asyncio.to_thread(run_oracle, req)
        oracle_msg = {
            "type": "oracle_simulation",
            "best_action": oracle_response.best_action,
            "top_score": oracle_response.results[0].safety_score if oracle_response.results else 0.0,
            "mode": oracle_response.mode
        }
        await manager.broadcast(oracle_msg)

        # ATHENA Planning (Non-blocking)
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
            log.error(f"ATHENA failed: {e}")

    for frame in sim.frames:
        await asyncio.sleep(0.05) # simulate realtime
        
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
            
            # Fallback for missing ML model: trigger anomaly if vitals drop significantly
            if not is_anomaly and vitals_payload["system_health"] < 0.85:
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
                }
                await manager.broadcast(sentinel_msg)
                
                # DIAGNOSIS (Non-blocking)
                # Same fix as SimulatorTelemetryProvider above — frame.timestamp
                # is sim-elapsed seconds, not a real epoch offset.
                dt_ts = datetime.now(timezone.utc)
                anomaly_event = AnomalyEvent(
                    anomaly_id="EVT-001",
                    timestamp=dt_ts,
                    flagged_subsystem="EPS",  # mock
                    severity=UrgencyLevel.HIGH,
                    telemetry_window=[]
                )
                
                provider = SimulatorTelemetryProvider(frame.state)
                # Run SHERLOCK in a separate thread to prevent blocking the event loop
                diagnosis = await asyncio.to_thread(sherlock_agent.diagnose, anomaly_event, provider)
                
                sherlock_msg = {
                    "type": "sherlock_diagnosis",
                    "primary_root_cause": diagnosis.primary_root_cause,
                    "causal_chain": diagnosis.causal_chain,
                    "confidence_score": diagnosis.confidence_score,
                    "urgency": diagnosis.urgency.value,
                    "time_to_critical": diagnosis.time_to_critical_estimate_minutes,
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
                    fault_name=diagnosis.primary_root_cause,
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
