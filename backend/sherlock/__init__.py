"""
SHERLOCK — Public Package Interface
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

Import surface for downstream agents (ATHENA, SCRIBE) and orchestrators.
Everything needed to use SHERLOCK is exported from here.
"""

from .agent import SherlockAgent
from .schemas import (
    AnomalyEvent,
    SherlockDiagnosis,
    SherlockDiagnosisError,
    SherlockGraphError,
    SeverityLevel,
    UrgencyLevel,
    TelemetrySnapshot,
)
from .graph import SatelliteGraph, SUBSYSTEMS
from .telemetry_interface import (
    TelemetryProvider,
    MockTelemetryProvider,
    PassthroughTelemetryProvider,
)

__all__ = [
    # Agent
    "SherlockAgent",
    # Input schemas
    "AnomalyEvent",
    "TelemetrySnapshot",
    # Output schemas
    "SherlockDiagnosis",
    # Enums
    "SeverityLevel",
    "UrgencyLevel",
    # Errors
    "SherlockDiagnosisError",
    "SherlockGraphError",
    # Graph
    "SatelliteGraph",
    "SUBSYSTEMS",
    # Telemetry
    "TelemetryProvider",
    "MockTelemetryProvider",
    "PassthroughTelemetryProvider",
]
