"""
AERO-ASTRA Physics Simulator — Pydantic State Schemas

All state and output data contracts for the simulator.

Field naming follows SHERLOCK's TelemetrySnapshot.parameters convention
for fields that overlap with existing agent schemas (battery_soc, cpu_load, etc.).

Note on watchdog_trips typing:
    Declared as `int` and enforced as a genuine discrete-event counter.
    The engine's InternalCounters tracks a float accumulator separately;
    watchdog_trips is only incremented by exactly 1 when a sustained-overload
    threshold crossing is confirmed — never fractionally. See transitions.py.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Subsystem state models
# ─────────────────────────────────────────────────────────────────────────────


class EPSState(BaseModel):
    """Electrical Power System subsystem state."""

    battery_soc: float = Field(
        ..., ge=0.0, le=1.0,
        description="Battery state of charge (0=empty, 1=full)",
    )
    solar_array_current: float = Field(
        ..., ge=0.0,
        description="Solar array output current in Amps",
    )
    bus_voltage: float = Field(
        ..., ge=0.0, le=36.0,
        description="Power bus voltage in Volts (nominal ~28 V)",
    )
    load_current: float = Field(
        ..., ge=0.0,
        description="Total load current drawn in Amps",
    )


class TCSState(BaseModel):
    """Thermal Control System subsystem state."""

    panel_temp: float = Field(
        ..., ge=-50.0, le=150.0,
        description="Primary panel temperature in °C",
    )
    battery_temp: float = Field(
        ..., ge=-50.0, le=100.0,
        description="Battery temperature in °C — directly coupled to EPS charge limits",
    )
    heater_active: bool = Field(
        ..., description="True if the survival heater is currently ON",
    )
    in_eclipse: bool = Field(
        ..., description="True if satellite is currently in orbital eclipse",
    )


class ADCSState(BaseModel):
    """Attitude Determination and Control System subsystem state."""

    attitude_error: float = Field(
        ..., ge=0.0, le=180.0,
        description="Absolute pointing error in degrees (0 = perfect nadir)",
    )
    reaction_wheel_speed: float = Field(
        ..., ge=-6000.0, le=6000.0,
        description="Reaction wheel speed in RPM",
    )


class OBCState(BaseModel):
    """On-Board Computer subsystem state."""

    free_memory_mb: float = Field(
        ..., ge=0.0, le=512.0,
        description="Available free memory in MB",
    )
    cpu_load: float = Field(
        ..., ge=0.0, le=1.0,
        description="CPU utilization fraction (0=idle, 1=saturated)",
    )
    watchdog_trips: int = Field(
        ..., ge=0,
        description=(
            "Cumulative count of watchdog reset events. "
            "Strict integer — never fractional. "
            "Incremented by exactly 1 per sustained overload event after cooldown."
        ),
    )


class TTCState(BaseModel):
    """Telemetry, Tracking and Command subsystem state."""

    signal_strength: float = Field(
        ..., ge=-120.0, le=-60.0,
        description="Received signal power in dBm",
    )
    bit_error_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description=(
            "Bit error rate fraction computed via sigmoid model "
            "relative to lock threshold (-90 dBm). "
            "Gradual S-curve degradation, not a step-function."
        ),
    )
    ground_contact_remaining: float = Field(
        ..., ge=0.0,
        description="Seconds until the current ground contact window ends",
    )


class PropulsionState(BaseModel):
    """Propulsion subsystem state."""

    fuel_remaining: float = Field(
        ..., ge=0.0,
        description="Remaining propellant mass in kg",
    )
    thruster_temp: float = Field(
        ..., ge=-20.0, le=200.0,
        description="Thruster temperature in °C",
    )


class SatelliteState(BaseModel):
    """
    Complete satellite state snapshot at a single simulation timestep.

    This is the canonical structure used internally and passed as input
    to run_monte_carlo. Use simulate_scenario to generate a sequence of these.
    """

    timestamp: float = Field(
        ..., ge=0.0,
        description="Simulation elapsed time in seconds",
    )
    eps: EPSState
    tcs: TCSState
    adcs: ADCSState
    obc: OBCState
    ttc: TTCState
    propulsion: PropulsionState
    active_fault: str | None = Field(
        default=None,
        description="Name of the active injected fault, or None if nominal",
    )
    fault_severity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Configured severity of the active fault (0=none, 1=maximum)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Output schemas for the two public entry points
# ─────────────────────────────────────────────────────────────────────────────


class SimulationFrame(BaseModel):
    """One timestep row in the simulate_scenario output time series."""

    timestamp: float
    state: SatelliteState
    fault_active: str | None
    fault_onset_time: float | None


class SimulationResult(BaseModel):
    """
    Full output of simulate_scenario.

    frames is the labeled time series: one SimulationFrame per dt step.
    Feed directly to a dashboard telemetry stream or use as labeled
    synthetic training data for other agents.
    """

    fault: str | None
    severity: float
    duration: float
    dt: float
    frames: list[SimulationFrame]


class MonteCarloOutcome(str, Enum):
    NOMINAL_RECOVERY = "nominal_recovery"
    DEGRADED_OPERATION = "degraded_operation"
    MISSION_LOSS = "mission_loss"


class MonteCarloResult(BaseModel):
    """
    Aggregate output of run_monte_carlo.

    ORACLE will consume this to rank proposed recovery actions.
    Rates sum to 1.0 across the three outcome categories.
    """

    proposed_action: str
    n_runs: int
    steps: int
    nominal_recovery_rate: float = Field(..., ge=0.0, le=1.0)
    degraded_operation_rate: float = Field(..., ge=0.0, le=1.0)
    mission_loss_rate: float = Field(..., ge=0.0, le=1.0)
    mean_final_battery_soc: float
    mean_final_attitude_error: float
    std_final_battery_soc: float
    outcome_counts: dict[str, int]
