"""
test_nominal.py — Verify subsystem values stay in sane ranges over a long undisturbed run.

Tests:
    - All field values stay within their Pydantic-declared bounds over 3600s
    - Eclipse cycle fires correctly (in_eclipse toggles, not stuck)
    - Battery SOC cycles plausibly with eclipse (charges in sunlight, drains in eclipse)
    - Attitude error hovers near equilibrium (not pinned at 0 — would look like a flatline)
    - watchdog_trips stays at 0 under nominal conditions
    - bit_error_rate stays low under nominal signal
"""

from __future__ import annotations

import pytest

from backend.simulator import simulate_scenario


@pytest.fixture(scope="module")
def nominal_run():
    """3600s nominal run — computed once and reused across tests."""
    return simulate_scenario(fault=None, duration=3600.0, dt=10.0, seed=1)


class TestNominalRanges:
    """All fields must stay within their physically declared bounds."""

    def test_battery_soc_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.eps.battery_soc <= 1.0, (
                f"battery_soc out of range at t={f.timestamp}"
            )

    def test_solar_current_non_negative(self, nominal_run):
        for f in nominal_run.frames:
            assert f.state.eps.solar_array_current >= 0.0

    def test_bus_voltage_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.eps.bus_voltage <= 36.0

    def test_panel_temp_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert -50.0 <= f.state.tcs.panel_temp <= 150.0, (
                f"panel_temp={f.state.tcs.panel_temp} out of range at t={f.timestamp}"
            )

    def test_battery_temp_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert -50.0 <= f.state.tcs.battery_temp <= 100.0

    def test_attitude_error_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.adcs.attitude_error <= 180.0

    def test_reaction_wheel_speed_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert -6000.0 <= f.state.adcs.reaction_wheel_speed <= 6000.0

    def test_free_memory_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.obc.free_memory_mb <= 512.0

    def test_cpu_load_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.obc.cpu_load <= 1.0

    def test_watchdog_trips_is_int_and_non_negative(self, nominal_run):
        for f in nominal_run.frames:
            trips = f.state.obc.watchdog_trips
            assert isinstance(trips, int), f"watchdog_trips is {type(trips)}, not int"
            assert trips >= 0

    def test_signal_strength_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert -120.0 <= f.state.ttc.signal_strength <= -60.0

    def test_ber_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert 0.0 <= f.state.ttc.bit_error_rate <= 1.0

    def test_ground_contact_non_negative(self, nominal_run):
        for f in nominal_run.frames:
            assert f.state.ttc.ground_contact_remaining >= 0.0

    def test_fuel_non_negative(self, nominal_run):
        for f in nominal_run.frames:
            assert f.state.propulsion.fuel_remaining >= 0.0

    def test_thruster_temp_bounds(self, nominal_run):
        for f in nominal_run.frames:
            assert -20.0 <= f.state.propulsion.thruster_temp <= 200.0


class TestNominalBehavior:
    """Verify physically correct qualitative behavior under nominal conditions."""

    def test_eclipse_cycles_fire(self, nominal_run):
        """Eclipse state should toggle at least once in a 3600s run (>half orbit)."""
        eclipse_states = [f.state.tcs.in_eclipse for f in nominal_run.frames]
        assert True in eclipse_states, "Satellite never entered eclipse in 3600s"
        assert False in eclipse_states, "Satellite stuck in eclipse for entire run"

    def test_battery_charges_in_sunlight(self, nominal_run):
        """Find a sunlight period and confirm SOC goes up, not down."""
        frames = nominal_run.frames
        for i in range(1, len(frames) - 1):
            if (
                not frames[i].state.tcs.in_eclipse
                and not frames[i - 1].state.tcs.in_eclipse
                and not frames[i + 1].state.tcs.in_eclipse
            ):
                # Three consecutive sunlight frames — SOC should be rising or stable
                # (may be slightly noisy, so check over a window)
                soc_start = frames[i].state.eps.battery_soc
                soc_later = frames[min(i + 30, len(frames) - 1)].state.eps.battery_soc
                # If started below 0.97, SOC should not have dropped significantly in sunlight
                if soc_start < 0.97:
                    assert soc_later >= soc_start - 0.05, (
                        f"SOC dropped from {soc_start:.3f} to {soc_later:.3f} in sunlight"
                    )
                break

    def test_attitude_not_pinned_at_zero(self, nominal_run):
        """
        ADCS uses proportional feedback — nominal attitude should hover near ~0.2°,
        NOT be pinned at exactly 0. A flatline at 0 would look like a SENTINEL anomaly.
        """
        errors = [f.state.adcs.attitude_error for f in nominal_run.frames]
        mean_error = sum(errors) / len(errors)
        # Should hover above 0.05° on average (not pinned)
        assert mean_error > 0.05, (
            f"Mean attitude_error={mean_error:.4f}° is suspiciously close to zero — "
            "proportional feedback should produce a small non-zero equilibrium"
        )
        # Should not be out of control
        assert mean_error < 10.0, f"Mean attitude_error={mean_error:.2f}° is unexpectedly large"

    def test_watchdog_zero_under_nominal(self, nominal_run):
        """Under nominal CPU load, no watchdog trips should occur."""
        final_trips = nominal_run.frames[-1].state.obc.watchdog_trips
        assert final_trips == 0, f"Unexpected watchdog trips in nominal run: {final_trips}"

    def test_ber_low_under_good_signal(self, nominal_run):
        """Nominal signal (-75 dBm) should produce low BER (< 0.1)."""
        for f in nominal_run.frames:
            if f.state.ttc.signal_strength > -85.0:   # well above lock threshold
                assert f.state.ttc.bit_error_rate < 0.1, (
                    f"BER={f.state.ttc.bit_error_rate:.4f} too high at "
                    f"signal={f.state.ttc.signal_strength:.1f}dBm"
                )

    def test_no_fault_label_in_nominal_run(self, nominal_run):
        """All frames should have fault_active=None."""
        for f in nominal_run.frames:
            assert f.fault_active is None
