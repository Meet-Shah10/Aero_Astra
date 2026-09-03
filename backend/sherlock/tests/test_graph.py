"""
SHERLOCK — Graph Unit Tests

Tests the SatelliteGraph class in isolation:
- Node/edge structure is correct
- Candidate set computation at depth=1 (default)
- Candidate set computation at depth=0 (self-only)
- Candidate set computation at depth=2
- Safety warning fires when candidate set > 4 nodes
- ValueError on unknown subsystem
- Cycle safety (TCS ↔ EPS doesn't loop infinitely)
"""

import logging
import pytest
from backend.sherlock.graph import SatelliteGraph, SUBSYSTEMS, CANDIDATE_SIZE_WARNING_THRESHOLD


@pytest.fixture
def graph() -> SatelliteGraph:
    return SatelliteGraph()


# ─────────────────────────────────────────────────────────────────────────────
# Structure tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphStructure:
    def test_node_count(self, graph):
        assert graph.graph.number_of_nodes() == 6

    def test_correct_nodes(self, graph):
        assert set(graph.graph.nodes()) == {"EPS", "TCS", "ADCS", "OBC", "TT&C", "Propulsion"}

    def test_edge_count(self, graph):
        assert graph.graph.number_of_edges() == 18

    def test_eps_feeds_all_others(self, graph):
        """EPS should have directed edges to every other subsystem."""
        eps_targets = {v for _, v in graph.graph.out_edges("EPS")}
        other_subsystems = {"TCS", "ADCS", "OBC", "TT&C", "Propulsion"}
        assert other_subsystems.issubset(eps_targets), (
            f"EPS missing edges to: {other_subsystems - eps_targets}"
        )

    def test_tcs_eps_cycle_exists(self, graph):
        """EPS → TCS and TCS → EPS should both exist (bidirectional thermal-power coupling)."""
        assert graph.graph.has_edge("EPS", "TCS")
        assert graph.graph.has_edge("TCS", "EPS")

    def test_edge_attributes_present(self, graph):
        """All edges must have dependency_type and description attributes."""
        for src, tgt, data in graph.graph.edges(data=True):
            assert "dependency_type" in data, f"Edge {src}→{tgt} missing dependency_type"
            assert "description" in data, f"Edge {src}→{tgt} missing description"
            assert data["dependency_type"], f"Edge {src}→{tgt} has empty dependency_type"
            assert data["description"], f"Edge {src}→{tgt} has empty description"

    def test_all_subsystems_constant(self):
        assert set(SUBSYSTEMS) == {"EPS", "TCS", "ADCS", "OBC", "TT&C", "Propulsion"}


# ─────────────────────────────────────────────────────────────────────────────
# Candidate computation: depth=0 (self-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidatesDepth0:
    def test_self_only(self, graph):
        for subsystem in SUBSYSTEMS:
            candidates = graph.get_candidates(subsystem, depth=0)
            assert candidates == {subsystem}, (
                f"At depth=0, {subsystem} should only return itself"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Candidate computation: depth=1 (default, direct predecessors)
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidatesDepth1:
    def test_flagged_always_in_candidates(self, graph):
        """The flagged subsystem itself must always be a candidate."""
        for subsystem in SUBSYSTEMS:
            candidates = graph.get_candidates(subsystem, depth=1)
            assert subsystem in candidates

    def test_eps_flagged_candidates(self, graph):
        """
        EPS predecessors at depth=1: TCS (thermal_feedback), ADCS (attitude_effect),
        OBC (command_control).
        """
        candidates = graph.get_candidates("EPS", depth=1)
        # EPS itself + its direct predecessors
        assert "EPS" in candidates
        assert "TCS" in candidates   # TCS → EPS (thermal_feedback)
        assert "ADCS" in candidates  # ADCS → EPS (attitude_effect)
        assert "OBC" in candidates   # OBC → EPS (command_control)
        # TT&C and Propulsion should NOT be in direct predecessors of EPS
        assert "TT&C" not in candidates
        assert "Propulsion" not in candidates

    def test_propulsion_flagged_candidates(self, graph):
        """
        Propulsion predecessors at depth=1: EPS (power_supply), TCS (thermal_stress).
        ADCS, OBC, TT&C should NOT be candidates.
        """
        candidates = graph.get_candidates("Propulsion", depth=1)
        assert "Propulsion" in candidates
        assert "EPS" in candidates
        assert "TCS" in candidates
        assert "ADCS" not in candidates
        assert "OBC" not in candidates
        assert "TT&C" not in candidates

    def test_ttc_flagged_candidates(self, graph):
        """
        TT&C predecessors at depth=1: EPS, ADCS, OBC, TT&C (self).
        TCS and Propulsion should NOT be candidates.
        """
        candidates = graph.get_candidates("TT&C", depth=1)
        assert "TT&C" in candidates
        assert "EPS" in candidates
        assert "ADCS" in candidates
        assert "OBC" in candidates
        assert "TCS" not in candidates
        assert "Propulsion" not in candidates

    def test_tcs_flagged_candidates(self, graph):
        """
        TCS predecessors at depth=1: EPS, ADCS, Propulsion, TCS (self).
        """
        candidates = graph.get_candidates("TCS", depth=1)
        assert "TCS" in candidates
        assert "EPS" in candidates
        assert "ADCS" in candidates
        assert "Propulsion" in candidates

    def test_obc_flagged_candidates(self, graph):
        """
        OBC predecessors at depth=1: EPS, TCS, TT&C, OBC (self).
        ADCS and Propulsion should NOT be candidates.
        """
        candidates = graph.get_candidates("OBC", depth=1)
        assert "OBC" in candidates
        assert "EPS" in candidates
        assert "TCS" in candidates
        assert "TT&C" in candidates
        assert "ADCS" not in candidates
        assert "Propulsion" not in candidates

    def test_adcs_flagged_candidates(self, graph):
        """
        ADCS predecessors at depth=1: EPS, TCS, OBC, Propulsion.
        TT&C is NOT a direct predecessor of ADCS.
        """
        candidates = graph.get_candidates("ADCS", depth=1)
        assert "ADCS" in candidates
        assert "EPS" in candidates
        assert "TCS" in candidates
        assert "OBC" in candidates
        assert "Propulsion" in candidates
        assert "TT&C" not in candidates

    def test_depth1_gives_genuine_narrowing_for_propulsion(self, graph):
        """
        Propulsion candidates at depth=1 should be < 6 (meaningful narrowing).
        This is the user's explicit check that depth=1 provides real filtering.
        """
        candidates = graph.get_candidates("Propulsion", depth=1)
        assert len(candidates) < 6, (
            f"Propulsion candidates at depth=1 should be < 6, got {len(candidates)}: {candidates}"
        )
        assert len(candidates) == 3  # Propulsion, EPS, TCS


# ─────────────────────────────────────────────────────────────────────────────
# Candidate size warning (the depth=3 regression test)
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidateSizeWarning:
    def test_warning_fires_for_full_set(self, graph, caplog):
        """
        When depth=3, many subsystems produce candidate sets covering all 6 nodes.
        The warning should fire for those cases.
        """
        with caplog.at_level(logging.WARNING, logger="backend.sherlock.graph"):
            candidates = graph.get_candidates("ADCS", depth=3)
        
        if len(candidates) > CANDIDATE_SIZE_WARNING_THRESHOLD:
            assert any("limited filtering power" in rec.message for rec in caplog.records), (
                "Expected candidate-size warning to fire when set > threshold"
            )

    def test_no_warning_for_propulsion_depth1(self, graph, caplog):
        """Propulsion at depth=1 produces only 3 candidates — no warning expected."""
        with caplog.at_level(logging.WARNING, logger="backend.sherlock.graph"):
            graph.get_candidates("Propulsion", depth=1)
        
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("limited filtering power" in m for m in warning_msgs)

    def test_threshold_constant(self):
        assert CANDIDATE_SIZE_WARNING_THRESHOLD == 4


# ─────────────────────────────────────────────────────────────────────────────
# Error cases
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidateErrors:
    def test_unknown_subsystem_raises_valueerror(self, graph):
        with pytest.raises(ValueError, match="Unknown subsystem"):
            graph.get_candidates("Battery", depth=1)

    def test_negative_depth_raises_valueerror(self, graph):
        with pytest.raises(ValueError, match="depth must be >= 0"):
            graph.get_candidates("EPS", depth=-1)


# ─────────────────────────────────────────────────────────────────────────────
# Cycle safety: TCS ↔ EPS should not infinite-loop at depth > 1
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleSafety:
    def test_depth2_does_not_infinite_loop(self, graph):
        """BFS with cycle should terminate, not loop forever."""
        # Should complete without hanging
        candidates = graph.get_candidates("TCS", depth=2)
        assert isinstance(candidates, set)
        assert len(candidates) > 0

    def test_depth10_terminates(self, graph):
        """Even an unreasonably large depth should terminate (all nodes visited, done)."""
        for subsystem in SUBSYSTEMS:
            candidates = graph.get_candidates(subsystem, depth=10)
            assert isinstance(candidates, set)
            assert len(candidates) <= len(SUBSYSTEMS)


# ─────────────────────────────────────────────────────────────────────────────
# describe_candidates and summary
# ─────────────────────────────────────────────────────────────────────────────

class TestDescribeAndSummary:
    def test_describe_candidates_includes_flagged(self, graph):
        desc = graph.describe_candidates("Propulsion", depth=1)
        assert "Propulsion" in desc

    def test_describe_candidates_includes_predecessors(self, graph):
        desc = graph.describe_candidates("Propulsion", depth=1)
        assert "EPS" in desc
        assert "TCS" in desc

    def test_summary_mentions_nodes_and_edges(self, graph):
        summary = graph.summary()
        assert "6 nodes" in summary
        assert "18 edges" in summary
        assert "EPS" in summary
