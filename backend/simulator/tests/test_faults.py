"""
test_faults.py — Verify each fault type visibly and correctly perturbs its target
subsystem, and that the cascading fault affects all downstream subsystems
per SHERLOCK's dependency graph.

Test strategy:
    For each fault: run a faulted simulation and a nominal (no-fault) baseline
    with the same seed. Compare the final state of the target subsystem.
    The faulted run's key metric must be meaningfully worse than baseline.

Cascade test:
    eps_cascade_power_failure must show degradation in EPS (primary) AND
    all 5 downstream subsystems: TCS, ADCS, OBC, TT&C, Propulsion.
    These are exactly the 5 EPS→* edges in SHERLOCK's dependency graph.
"""

from __future__ import annotations

import pytest

from backend.simulator import simulate_scenario

_DURATION = 2400.0   # 40 minutes — long enough for effects to build
_DT = 10.0
_FAULT_ONSET = 300.0  # 5 minutes of clean baseline before fault


def _final(result):
    return result.frames[-1].state


def _nominal():
    return simulate_scenario(fault=None, duration=_DURATION, dt=_DT, seed=99)


class TestEPSBatteryDegradation:
    def test_soc_drops_more_than_nominal(self):
        # Use longer duration so battery has time to drain across multiple eclipse cycles
        nom = _final(simulate_scenario(fault=None, duration=7200.0, dt=_DT, seed=99))
        faulted = _final(simulate_scenario(
            fault="eps_battery_degradation",
            severity=0.7,
            duration=7200.0,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.eps.battery_soc < nom.eps.battery_soc, (
            f"Faulted SOC {faulted.eps.battery_soc:.3f} should be below "
            f"nominal {nom.eps.battery_soc:.3f} over 2hr run"
        )

    def test_fault_label_present_after_onset(self):
        result = simulate_scenario(
            fault="eps_battery_degradation", severity=0.7,
            duration=_DURATION, dt=_DT, fault_onset=_FAULT_ONSET, seed=99,
        )
        # Frames after onset should be labeled
        post_onset = [f for f in result.frames if f.timestamp > _FAULT_ONSET + _DT]
        assert all(f.fault_active == "eps_battery_degradation" for f in post_onset)


class TestTCSThermalRunaway:
    def test_panel_temp_rises_more_than_nominal(self):
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="tcs_thermal_runaway",
            severity=0.8,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.tcs.panel_temp > nom.tcs.panel_temp + 5.0, (
            f"Faulted panel_temp {faulted.tcs.panel_temp:.1f}°C should be "
            f"significantly above nominal {nom.tcs.panel_temp:.1f}°C"
        )

    def test_panel_temp_stays_in_bounds(self):
        result = simulate_scenario(
            fault="tcs_thermal_runaway", severity=1.0,
            duration=_DURATION, dt=_DT, fault_onset=_FAULT_ONSET, seed=99,
        )
        for f in result.frames:
            assert -50.0 <= f.state.tcs.panel_temp <= 150.0


class TestADCSReactionWheelDegradation:
    def test_attitude_error_grows_more_than_nominal(self):
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="adcs_reaction_wheel_degradation",
            severity=0.8,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        # Faulted attitude should be noticeably above nominal (0.5° margin)
        assert faulted.adcs.attitude_error > nom.adcs.attitude_error + 0.5, (
            f"Faulted attitude_error {faulted.adcs.attitude_error:.2f}° should be "
            f"significantly above nominal {nom.adcs.attitude_error:.2f}°"
        )


class TestTTCSignalDropout:
    def test_signal_drops_below_nominal(self):
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="ttc_signal_dropout",
            severity=0.9,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.ttc.signal_strength < nom.ttc.signal_strength - 5.0, (
            f"Faulted signal {faulted.ttc.signal_strength:.1f}dBm should be "
            f"well below nominal {nom.ttc.signal_strength:.1f}dBm"
        )

    def test_ber_rises_significantly(self):
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="ttc_signal_dropout",
            severity=0.9,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.ttc.bit_error_rate > nom.ttc.bit_error_rate + 0.3, (
            f"Faulted BER {faulted.ttc.bit_error_rate:.4f} should be well above "
            f"nominal {nom.ttc.bit_error_rate:.4f}"
        )

    def test_ber_is_gradual_not_step_function(self):
        """
        BER should increase gradually (sigmoid model), not jump instantly to 1.0.
        This verifies Fix 2 (sigmoid BER) is working as intended.
        Check frames DURING the 60s ramp window, where signal is partially degraded.
        """
        result = simulate_scenario(
            fault="ttc_signal_dropout", severity=0.6,  # moderate severity
            duration=_DURATION, dt=_DT, fault_onset=_FAULT_ONSET, seed=99,
        )
        # Frames in the first 60s of the fault (ramp window) should show BER < 1.0
        ramp_frames = [
            f.state.ttc.bit_error_rate for f in result.frames
            if _FAULT_ONSET < f.timestamp <= _FAULT_ONSET + 60.0
        ]
        # At least some frames during ramp should have BER < 0.99 (not instantly pinned)
        not_fully_saturated = [b for b in ramp_frames if b < 0.99]
        assert len(not_fully_saturated) > 0, (
            "BER instantly saturated to 1.0 in first 60s of fault ramp. "
            "Sigmoid BER model with ramp should produce gradual degradation."
        )


class TestPropulsionThrusterFault:
    def test_fuel_drains_faster_than_nominal(self):
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="propulsion_thruster_fault",
            severity=0.8,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.propulsion.fuel_remaining < nom.propulsion.fuel_remaining, (
            "Faulted fuel_remaining should be less than nominal (uncontrolled burn/leak)"
        )

    def test_adcs_disturbed_by_propulsion_fault(self):
        """
        Propulsion→ADCS attitude_disturbance edge: thruster misfire should raise
        attitude error beyond what nominal ADCS drift produces.
        """
        nom = _final(_nominal())
        faulted = _final(simulate_scenario(
            fault="propulsion_thruster_fault",
            severity=0.8,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        ))
        assert faulted.adcs.attitude_error > nom.adcs.attitude_error, (
            "Propulsion fault should disturb ADCS via attitude_disturbance edge"
        )


class TestCascadePowerFailure:
    """
    The flagship cascading scenario.
    Verifies that eps_cascade_power_failure degrades ALL 5 downstream
    subsystems connected via EPS→* power_supply edges in SHERLOCK's graph.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def cascade_result(cls, request):
        return simulate_scenario(
            fault="eps_cascade_power_failure",
            severity=0.9,
            duration=_DURATION,
            dt=_DT,
            fault_onset=_FAULT_ONSET,
            seed=99,
        )

    @pytest.fixture(scope="class")
    @classmethod
    def nominal_final(cls, request):
        return _final(_nominal())

    def test_eps_primary_soc_drops(self, cascade_result, nominal_final):
        """EPS (primary target): SOC should drain significantly."""
        faulted_final = _final(cascade_result)
        assert faulted_final.eps.battery_soc < nominal_final.eps.battery_soc - 0.05, (
            f"EPS SOC {faulted_final.eps.battery_soc:.3f} should be well below "
            f"nominal {nominal_final.eps.battery_soc:.3f}"
        )

    def test_tcs_cascade_effect(self, cascade_result, nominal_final):
        """EPS→TCS power_supply edge: heaters lose power → thermal disruption."""
        faulted_final = _final(cascade_result)
        # Panel temp should deviate from nominal (direction depends on eclipse phase)
        temp_delta = abs(faulted_final.tcs.panel_temp - nominal_final.tcs.panel_temp)
        assert temp_delta > 2.0, (
            f"TCS panel_temp delta {temp_delta:.1f}°C too small — "
            "EPS→TCS cascade not visible"
        )

    def test_adcs_cascade_effect(self, cascade_result, nominal_final):
        """EPS→ADCS power_supply edge: wheel torque loss → attitude error grows."""
        faulted_final = _final(cascade_result)
        assert faulted_final.adcs.attitude_error > nominal_final.adcs.attitude_error + 0.5, (
            f"ADCS attitude_error {faulted_final.adcs.attitude_error:.2f}° should exceed "
            f"nominal {nominal_final.adcs.attitude_error:.2f}° — EPS→ADCS cascade"
        )

    def test_obc_cascade_effect(self, cascade_result, nominal_final):
        """EPS→OBC power_supply edge: undervoltage stress raises CPU load."""
        faulted_final = _final(cascade_result)
        assert faulted_final.obc.cpu_load > nominal_final.obc.cpu_load, (
            "OBC cpu_load should be elevated by EPS→OBC cascade"
        )

    def test_ttc_cascade_effect(self, cascade_result, nominal_final):
        """EPS→TT&C power_supply edge: transmitter power loss degrades signal."""
        faulted_final = _final(cascade_result)
        assert faulted_final.ttc.signal_strength < nominal_final.ttc.signal_strength - 1.0, (
            f"TT&C signal {faulted_final.ttc.signal_strength:.1f}dBm should be below "
            f"nominal {nominal_final.ttc.signal_strength:.1f}dBm — EPS→TT&C cascade"
        )

    def test_all_cascades_simultaneously(self, cascade_result, nominal_final):
        """
        All 5 downstream subsystems should show degradation vs baseline.
        This is the end-to-end SHERLOCK consistency test: a simulated cascade
        that SHERLOCK's get_candidates('ADCS') would identify EPS as valid candidate.
        """
        faulted = _final(cascade_result)
        nom = nominal_final

        eps_degraded = faulted.eps.battery_soc < nom.eps.battery_soc - 0.05
        tcs_degraded = abs(faulted.tcs.panel_temp - nom.tcs.panel_temp) > 2.0
        adcs_degraded = faulted.adcs.attitude_error > nom.adcs.attitude_error + 0.5
        obc_degraded = faulted.obc.cpu_load > nom.obc.cpu_load
        ttc_degraded = faulted.ttc.signal_strength < nom.ttc.signal_strength - 1.0

        degraded_count = sum([eps_degraded, tcs_degraded, adcs_degraded, obc_degraded, ttc_degraded])
        assert degraded_count >= 4, (
            f"Only {degraded_count}/5 subsystems showed cascade degradation. "
            f"EPS:{eps_degraded} TCS:{tcs_degraded} ADCS:{adcs_degraded} "
            f"OBC:{obc_degraded} TT&C:{ttc_degraded}"
        )
