"""
SHERLOCK — Simulator-Backed TelemetryProvider

Adapts backend.simulator.schemas.SatelliteState into SHERLOCK's
TelemetrySnapshot contract, per the extension point that telemetry_interface.py
was already designed for: "Future integration with the Physics Simulator ...
only requires implementing TelemetryProvider — no changes to agent.py."

Parameter names below match MockTelemetryProvider's `_NOMINAL_TELEMETRY` keys
so existing SHERLOCK prompts/tests see the same shape of data whether it came
from the mock or the live simulator. Fields with no direct simulator
equivalent (payload_temp_c, radiator_temp_c, star_tracker_confidence, etc.)
are omitted rather than invented — SHERLOCK tolerates partial snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.simulator.schemas import SatelliteState

from .schemas import TelemetrySnapshot
from .telemetry_interface import TelemetryProvider

# Initial fuel load in _INITIAL_STATE (backend/simulator/engine.py) — used as
# the 100% reference point for propellant_remaining_pct.
_FULL_FUEL_KG = 48.5
# Free-memory ceiling from SatelliteState's OBCState.free_memory_mb field bound.
_MAX_FREE_MEMORY_MB = 512.0


def _clock() -> datetime:
    return datetime.now(timezone.utc)


class SimulatorTelemetryProvider(TelemetryProvider):
    """
    Wraps a single SatelliteState snapshot from the physics digital twin.

    Usage:
        state = latest_frame.state  # from simulate_scenario() / the live sim loop
        provider = SimulatorTelemetryProvider(state)
        diagnosis = run_sherlock(event, telemetry_provider=provider)

    Call `update(state)` each tick to point the provider at the newest frame
    without constructing a new object per timestep.
    """

    def __init__(self, state: SatelliteState) -> None:
        self._state = state

    def update(self, state: SatelliteState) -> None:
        self._state = state

    def get_subsystem_snapshot(self, subsystem: str) -> TelemetrySnapshot | None:
        s = self._state
        builders = {
            "EPS": lambda: {
                "battery_voltage_v": s.eps.bus_voltage,
                "battery_soc_pct": s.eps.battery_soc * 100.0,
                "solar_current_a": s.eps.solar_array_current,
                "bus_voltage_v": s.eps.bus_voltage,
                "charge_current_a": s.eps.load_current,
            },
            "TCS": lambda: {
                "battery_temp_c": s.tcs.battery_temp,
                "panel_temp_c": s.tcs.panel_temp,
            },
            "ADCS": lambda: {
                "pointing_error_deg": s.adcs.attitude_error,
                "reaction_wheel_rpm": s.adcs.reaction_wheel_speed,
            },
            "OBC": lambda: {
                "cpu_load_pct": s.obc.cpu_load * 100.0,
                "ram_usage_pct": (1.0 - s.obc.free_memory_mb / _MAX_FREE_MEMORY_MB) * 100.0,
                "watchdog_trips_1h": float(s.obc.watchdog_trips),
            },
            "TT&C": lambda: {
                "signal_strength_dbm": s.ttc.signal_strength,
                "bit_error_rate": s.ttc.bit_error_rate,
            },
            "Propulsion": lambda: {
                "propellant_remaining_pct": (s.propulsion.fuel_remaining / _FULL_FUEL_KG) * 100.0,
                "thruster_temp_c": s.propulsion.thruster_temp,
            },
        }

        builder = builders.get(subsystem)
        if builder is None:
            return None

        return TelemetrySnapshot(
            subsystem=subsystem,
            parameters=builder(),
            timestamp=_clock(),
        )
