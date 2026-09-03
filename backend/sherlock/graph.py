"""
SHERLOCK — Satellite Subsystem Dependency Graph
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

Builds a directed NetworkX graph representing physical/functional dependency
relationships between the 6 satellite subsystems. An edge A → B means:
"a fault in A can propagate to or cause a fault in B."

Candidate determination:
  Given a flagged subsystem S, the graph computes the set of subsystems
  that are physically capable of causing the anomaly observed in S.
  This is the set of direct predecessors of S in the graph, plus S itself.

  Default search depth is 1 (direct predecessors only). This is intentionally
  conservative — at depth ≥ 2 with this edge density, the candidate set
  degenerates towards the full node set and loses its filtering power.
  Depth is a configurable parameter for future adjustment.

Candidate-set size warning:
  If the computed candidate set covers more than WARNING_THRESHOLD nodes,
  SHERLOCK logs a warning. This is a safety tripwire to detect when the
  constraint has lost practical filtering power.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

#: The 6 modelled satellite subsystems.
SUBSYSTEMS: list[str] = ["EPS", "TCS", "ADCS", "OBC", "TT&C", "Propulsion"]

#: If the candidate set covers more than this many nodes, emit a warning.
#: At 6 total nodes, >4 means only 1 node is actually ruled out.
CANDIDATE_SIZE_WARNING_THRESHOLD: int = 4

#: Default predecessor search depth.
DEFAULT_CANDIDATE_DEPTH: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Edge definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DependencyEdge:
    source: str
    target: str
    dependency_type: str
    description: str


# All 18 edges. Each represents a real physical/functional dependency.
# An edge (source → target) means: a fault in `source` can cause a fault in `target`.
DEPENDENCY_EDGES: list[DependencyEdge] = [
    # ── EPS as fault source ───────────────────────────────────────────────────
    DependencyEdge(
        "EPS", "TCS", "power_supply",
        "Heaters, coolers, and heat pipes are EPS-powered; undervoltage disables thermal control"
    ),
    DependencyEdge(
        "EPS", "ADCS", "power_supply",
        "Reaction wheels, magnetorquers, and star trackers draw EPS power; loss causes attitude loss"
    ),
    DependencyEdge(
        "EPS", "OBC", "power_supply",
        "OBC is directly EPS-fed; undervoltage or power glitch causes resets or data corruption"
    ),
    DependencyEdge(
        "EPS", "TT&C", "power_supply",
        "RF transmitters are among the highest EPS loads; power loss silences comms"
    ),
    DependencyEdge(
        "EPS", "Propulsion", "power_supply",
        "Thruster valve actuators and propulsion controllers are EPS-powered"
    ),

    # ── TCS as fault source ───────────────────────────────────────────────────
    DependencyEdge(
        "TCS", "ADCS", "thermal_stress",
        "Gyroscopes and star trackers have tight thermal ranges; overtemp causes drift or shutdown"
    ),
    DependencyEdge(
        "TCS", "OBC", "thermal_stress",
        "Excessive board temperature causes clock errors, bit-flips, or thermal throttling/reset"
    ),
    DependencyEdge(
        "TCS", "EPS", "thermal_feedback",
        "Battery temperature directly limits charge/discharge capacity (bidirectional coupling)"
    ),
    DependencyEdge(
        "TCS", "Propulsion", "thermal_stress",
        "Propellant can freeze or expand outside thermal range; thruster performance degrades"
    ),

    # ── ADCS as fault source ──────────────────────────────────────────────────
    DependencyEdge(
        "ADCS", "TCS", "attitude_effect",
        "Wrong attitude rotates panels away from sun, altering thermal balance and solar input"
    ),
    DependencyEdge(
        "ADCS", "EPS", "attitude_effect",
        "Off-pointing reduces solar panel power generation; prolonged mispointing drains battery"
    ),
    DependencyEdge(
        "ADCS", "TT&C", "pointing",
        "Antenna must be Earth-pointed for ground link; attitude fault de-points antenna"
    ),

    # ── OBC as fault source ───────────────────────────────────────────────────
    DependencyEdge(
        "OBC", "ADCS", "command_control",
        "ADCS receives guidance commands from OBC; OBC fault halts the control loop"
    ),
    DependencyEdge(
        "OBC", "TT&C", "command_control",
        "OBC routes all downlink/uplink data; OBC fault silences or corrupts communications"
    ),
    DependencyEdge(
        "OBC", "EPS", "command_control",
        "OBC manages EPS load-shedding and charge state; fault causes power mismanagement"
    ),

    # ── TT&C as fault source ──────────────────────────────────────────────────
    DependencyEdge(
        "TT&C", "OBC", "data_link",
        "Loss of uplink means no ground commands reach OBC; satellite operates blind"
    ),

    # ── Propulsion as fault source ────────────────────────────────────────────
    DependencyEdge(
        "Propulsion", "ADCS", "attitude_disturbance",
        "Thruster misfire or leak creates uncontrolled torque; ADCS must compensate or saturates"
    ),
    DependencyEdge(
        "Propulsion", "TCS", "thermal_output",
        "Thrusters generate significant local heat during burns; affects thermal balance"
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# SatelliteGraph
# ─────────────────────────────────────────────────────────────────────────────

class SatelliteGraph:
    """
    Directed dependency graph of satellite subsystems.

    Nodes = subsystems. Edge A → B = "fault in A can propagate to B."

    Primary method: get_candidates(flagged_subsystem, depth) returns the
    set of subsystems that the graph identifies as physically-valid root
    cause candidates for an observed fault in `flagged_subsystem`.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._build()

    def _build(self) -> None:
        """Populate nodes and edges from DEPENDENCY_EDGES."""
        self._graph.add_nodes_from(SUBSYSTEMS)
        for edge in DEPENDENCY_EDGES:
            self._graph.add_edge(
                edge.source,
                edge.target,
                dependency_type=edge.dependency_type,
                description=edge.description,
            )
        log.info(
            "SatelliteGraph built: %d nodes, %d edges",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def graph(self) -> nx.DiGraph:
        """Read-only access to the underlying NetworkX graph."""
        return self._graph

    def get_candidates(
        self,
        flagged_subsystem: str,
        depth: int = DEFAULT_CANDIDATE_DEPTH,
    ) -> set[str]:
        """
        Compute the set of subsystems that are valid root cause candidates
        for an observed fault in `flagged_subsystem`.

        Algorithm:
            candidates = {flagged_subsystem}
                       ∪ {all predecessors within `depth` hops}

        The flagged subsystem itself is always included — it may be
        self-faulting (primary fault, not a victim of upstream cascades).

        Args:
            flagged_subsystem: The subsystem where the anomaly was observed.
            depth: Maximum upstream hops to search. Default 1 (direct only).
                   Keep at 1 unless you have empirical data justifying more.

        Returns:
            Set of subsystem name strings.

        Raises:
            ValueError: If flagged_subsystem is not in the graph.
        """
        if flagged_subsystem not in self._graph:
            valid = sorted(self._graph.nodes())
            raise ValueError(
                f"Unknown subsystem '{flagged_subsystem}'. "
                f"Valid subsystems: {valid}"
            )

        if depth < 0:
            raise ValueError(f"depth must be >= 0, got {depth}")

        candidates: set[str] = {flagged_subsystem}

        if depth == 0:
            # Only self — useful for strict testing
            pass
        elif depth == 1:
            # Direct predecessors only (most common, recommended)
            candidates.update(self._graph.predecessors(flagged_subsystem))
        else:
            # BFS/DFS up to `depth` hops upstream
            # nx.ancestors gives ALL reachable ancestors (unbounded).
            # We implement depth-bounded BFS ourselves.
            visited: set[str] = {flagged_subsystem}
            frontier: set[str] = {flagged_subsystem}
            for _ in range(depth):
                next_frontier: set[str] = set()
                for node in frontier:
                    for pred in self._graph.predecessors(node):
                        if pred not in visited:
                            visited.add(pred)
                            next_frontier.add(pred)
                frontier = next_frontier
                candidates.update(frontier)
                if not frontier:
                    break  # Graph exhausted before depth limit

        # ── Safety tripwire ───────────────────────────────────────────────────
        n_total = self._graph.number_of_nodes()
        if len(candidates) > CANDIDATE_SIZE_WARNING_THRESHOLD:
            log.warning(
                "SHERLOCK candidate set for '%s' (depth=%d) covers %d/%d nodes: %s. "
                "The constraint has limited filtering power. Consider reducing depth "
                "or reviewing graph edge density.",
                flagged_subsystem,
                depth,
                len(candidates),
                n_total,
                sorted(candidates),
            )

        log.debug(
            "Candidates for '%s' at depth=%d: %s",
            flagged_subsystem,
            depth,
            sorted(candidates),
        )
        return candidates

    def get_edge_description(self, source: str, target: str) -> str | None:
        """Return the human-readable edge description, or None if no edge exists."""
        edge_data = self._graph.get_edge_data(source, target)
        if edge_data is None:
            return None
        return edge_data.get("description", "")

    def get_dependency_type(self, source: str, target: str) -> str | None:
        """Return the dependency type label for an edge, or None if no edge exists."""
        edge_data = self._graph.get_edge_data(source, target)
        if edge_data is None:
            return None
        return edge_data.get("dependency_type", "")

    def describe_candidates(
        self,
        flagged_subsystem: str,
        depth: int = DEFAULT_CANDIDATE_DEPTH,
    ) -> str:
        """
        Returns a human-readable string describing the candidate set and
        the edges that make each candidate valid. Used in LLM prompts.
        """
        candidates = self.get_candidates(flagged_subsystem, depth)
        lines: list[str] = []

        for candidate in sorted(candidates):
            if candidate == flagged_subsystem:
                lines.append(
                    f"  - {candidate} [self — may be primary/self-faulting subsystem]"
                )
            else:
                # Find the direct edge that makes this a valid predecessor
                # (may be via intermediate nodes at depth>1)
                edge_data = self._graph.get_edge_data(candidate, flagged_subsystem)
                if edge_data:
                    lines.append(
                        f"  - {candidate} "
                        f"[{edge_data['dependency_type']}] -> {flagged_subsystem}: "
                        f"{edge_data['description']}"
                    )
                else:
                    # Indirect predecessor — find the path
                    try:
                        path = nx.shortest_path(
                            self._graph, candidate, flagged_subsystem
                        )
                        path_str = " → ".join(path)
                        lines.append(
                            f"  - {candidate} [indirect via {path_str}]"
                        )
                    except nx.NetworkXNoPath:
                        lines.append(f"  - {candidate}")

        return "\n".join(lines)

    def summary(self) -> str:
        """Return a brief text summary of the graph structure."""
        lines = [
            f"Satellite Dependency Graph: {self._graph.number_of_nodes()} nodes, "
            f"{self._graph.number_of_edges()} edges",
            "",
            "Edges (A → B means: fault in A can cause fault in B):",
        ]
        for src, tgt, data in sorted(
            self._graph.edges(data=True), key=lambda e: (e[0], e[1])
        ):
            lines.append(
                f"  {src} -> {tgt}  [{data['dependency_type']}]  "
                f"{data['description']}"
            )
        return "\n".join(lines)
