"""
SHERLOCK — Telemetry Data Access Layer
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

Abstract interface for fetching current subsystem telemetry snapshots.
SHERLOCK depends on this abstraction, not on any concrete data source.
This means:
  - Tests use MockTelemetryProvider with realistic synthetic values.
  - Standalone demo uses PassthroughTelemetryProvider (reads from AnomalyEvent).
  - Future integration with the Physics Simulator or a real data bus
    only requires implementing TelemetryProvider — no changes to agent.py.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from .schemas import AnomalyEvent, TelemetrySnapshot

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Base
# ─────────────────────────────────────────────────────────────────────────────

class TelemetryProvider(ABC):
    """
    Abstract data access layer for subsystem telemetry.

    Implementors must return the latest known snapshot for a given subsystem,
    or None if the data is unavailable. Returning None is valid — SHERLOCK
    will note data unavailability in its prompt but still proceed.
    """

    @abstractmethod
    def get_subsystem_snapshot(self, subsystem: str) -> TelemetrySnapshot | None:
        """
        Return the latest telemetry snapshot for the given subsystem.

        Args:
            subsystem: Subsystem identifier, e.g. "EPS"

        Returns:
            TelemetrySnapshot if data is available, None otherwise.
        """
        ...

    def get_snapshots_for_candidates(
        self, candidates: set[str]
    ) -> dict[str, TelemetrySnapshot | None]:
        """
        Convenience: fetch snapshots for all subsystems in the candidate set.
        Returns a dict of {subsystem: snapshot_or_None}.
        """
        return {sub: self.get_subsystem_snapshot(sub) for sub in sorted(candidates)}

    def format_for_prompt(self, snapshots: dict[str, TelemetrySnapshot | None]) -> str:
        """
        Format a dict of snapshots into a human-readable string for LLM prompt injection.
        """
        if not snapshots:
            return "  (No telemetry available)"

        lines: list[str] = []
        for subsystem, snapshot in sorted(snapshots.items()):
            if snapshot is None:
                lines.append(f"  {subsystem}: [data unavailable]")
            else:
                params_str = ", ".join(
                    f"{k}={v:.4g}" for k, v in snapshot.parameters.items()
                )
                lines.append(f"  {subsystem}: {params_str}  (at {snapshot.timestamp.isoformat()})")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PassthroughTelemetryProvider
# ─────────────────────────────────────────────────────────────────────────────

class PassthroughTelemetryProvider(TelemetryProvider):
    """
    Reads telemetry directly from the AnomalyEvent's telemetry_window.

    This is the default provider when SHERLOCK is used standalone or in tests
    without a live telemetry source. It aggregates the telemetry_window rows
    (taking the last value for each parameter) and returns them as a snapshot
    for the flagged subsystem. All other subsystems return None.

    This design means SHERLOCK is fully functional out-of-the-box using only
    the information in the AnomalyEvent, with no external dependencies.
    """

    def __init__(self, event: AnomalyEvent) -> None:
        self._event = event
        self._snapshot = self._build_snapshot()

    def _build_snapshot(self) -> TelemetrySnapshot | None:
        if not self._event.telemetry_window:
            return None

        # Aggregate: take the last non-None value for each parameter
        params: dict[str, float] = {}
        for row in self._event.telemetry_window:
            for k, v in row.items():
                if isinstance(v, (int, float)):
                    params[k] = float(v)

        if not params:
            return None

        return TelemetrySnapshot(
            subsystem=self._event.flagged_subsystem,
            parameters=params,
            timestamp=self._event.timestamp,
        )

    def get_subsystem_snapshot(self, subsystem: str) -> TelemetrySnapshot | None:
        """Returns snapshot for the flagged subsystem; None for all others."""
        if subsystem == self._event.flagged_subsystem:
            return self._snapshot
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MockTelemetryProvider
# ─────────────────────────────────────────────────────────────────────────────

# Realistic nominal and fault-condition telemetry values for each subsystem.
# Used in tests and demo scenarios to provide plausible context to the LLM.
_NOMINAL_TELEMETRY: dict[str, dict[str, float]] = {
    "EPS": {
        "battery_voltage_v": 28.4,
        "battery_soc_pct": 87.0,
        "solar_current_a": 4.2,
        "bus_voltage_v": 28.0,
        "charge_current_a": 1.8,
    },
    "TCS": {
        "battery_temp_c": 18.0,
        "panel_temp_c": 45.0,
        "payload_temp_c": 22.0,
        "radiator_temp_c": 35.0,
        "obc_board_temp_c": 28.0,
    },
    "ADCS": {
        "pointing_error_deg": 0.05,
        "reaction_wheel_rpm": 1200.0,
        "magnetorquer_current_a": 0.3,
        "star_tracker_confidence": 0.98,
        "angular_rate_deg_s": 0.001,
    },
    "OBC": {
        "cpu_load_pct": 42.0,
        "ram_usage_pct": 61.0,
        "reboot_count_1h": 0.0,
        "uptime_hours": 2147.0,
        "watchdog_trips_1h": 0.0,
    },
    "TT&C": {
        "signal_strength_dbm": -87.0,
        "data_rate_kbps": 9600.0,
        "link_margin_db": 12.0,
        "tx_power_w": 2.0,
        "last_contact_minutes_ago": 14.0,
    },
    "Propulsion": {
        "tank_pressure_bar": 22.5,
        "propellant_remaining_pct": 73.0,
        "thruster_temp_c": 20.0,
        "last_burn_duration_s": 0.0,
        "valve_status": 0.0,  # 0=closed, 1=open
    },
}


class MockTelemetryProvider(TelemetryProvider):
    """
    Returns realistic synthetic telemetry snapshots.

    By default, returns nominal values for all subsystems. Use
    `inject_fault(subsystem, overrides)` to simulate fault conditions
    for specific subsystems in test scenarios.

    Example:
        provider = MockTelemetryProvider()
        provider.inject_fault("EPS", {"battery_voltage_v": 21.3, "battery_soc_pct": 18.0})
    """

    def __init__(self) -> None:
        import copy
        self._data: dict[str, dict[str, float]] = copy.deepcopy(_NOMINAL_TELEMETRY)

    def inject_fault(self, subsystem: str, overrides: dict[str, float]) -> None:
        """
        Override specific telemetry parameters to simulate a fault condition.

        Args:
            subsystem: Target subsystem identifier.
            overrides: Dict of parameter_name → fault_value.
        """
        if subsystem not in self._data:
            raise ValueError(
                f"Unknown subsystem '{subsystem}'. "
                f"Valid: {sorted(self._data.keys())}"
            )
        self._data[subsystem].update(overrides)
        log.debug("MockTelemetryProvider: injected fault on %s: %s", subsystem, overrides)

    def get_subsystem_snapshot(self, subsystem: str) -> TelemetrySnapshot | None:
        if subsystem not in self._data:
            log.warning(
                "MockTelemetryProvider: unknown subsystem '%s', returning None", subsystem
            )
            return None
        return TelemetrySnapshot(
            subsystem=subsystem,
            parameters=dict(self._data[subsystem]),
            timestamp=datetime.now(timezone.utc),
        )
