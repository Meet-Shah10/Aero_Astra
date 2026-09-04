import asyncio
from backend.simulator.schemas import SatelliteState, EPSState, ADCSState, TCSState, OBCState, TTCState
from backend.simulator.engine import run_monte_carlo
from backend.simulator.recovery import RECOVERY_CATALOG

def test_dt(dt_val):
    state = SatelliteState(
        timestamp=120.0,
        eps=EPSState(battery_soc=0.6, solar_array_current=2.1, bus_voltage=26.4, load_current=3.8),
        adcs=ADCSState(attitude_error=0.12, reaction_wheel_speed=1200.0),
        tcs=TCSState(panel_temp=76.3, internal_temp=22.1, heater_active=False),
        obc=OBCState(cpu_load=0.45, memory_usage=0.55, watchdog_trips=0),
        ttc=TTCState(signal_strength=-85.0, bit_error_rate=1e-5, lock_status=True)
    )

    print(f"\n--- Testing dt={dt_val} ---")
    for action in RECOVERY_CATALOG.keys():
        res = run_monte_carlo(current_state=state, proposed_action=action, n_runs=100, steps=300, dt=dt_val, fault="tcs_thermal_runaway", fault_severity=0.75)
        print(f"{action}: {res.nominal_recovery_rate:.2f} nominal, {res.degraded_operation_rate:.2f} degraded, {res.mission_loss_rate:.2f} loss")

test_dt(15.0)
test_dt(20.0)
test_dt(25.0)
test_dt(30.0)
test_dt(40.0)
