def calculate_vitals(state) -> dict:
    """
    Computes heuristic health scores (0.0 to 1.0) for satellite subsystems,
    purely from real telemetry values — no fault-label shortcuts.

    Thresholds are calibrated against this simulator's actual behavior at
    api.py's real runtime settings (severity=0.7, duration=600s), not
    against slower multi-hour engineering limits — a threshold that's
    physically correct but only reached after an hour is useless as a
    live-demo trigger. See roadmap.md §2/§4 for the empirical numbers this
    was tuned against (measured directly, not guessed).

    An earlier version of this function had
    `if state.active_fault == "eps_cascade_power_failure": eps_score -= ...`
    — reading the ground-truth fault label instead of deriving anything
    from telemetry. That's removed. Every score below comes only from
    state values a real SENTINEL would actually observe.
    """
    # 1. EPS Health — bus_voltage calibrated to roadmap.md's warn/critical/
    #    mission_loss line (25V/22V/18V), battery_soc to the 50% warn line.
    soc = state.eps.battery_soc
    vbus = state.eps.bus_voltage

    eps_score = 1.0
    if soc < 0.5:
        eps_score -= (0.5 - soc) * 2.0
    if vbus < 25.0:
        eps_score -= (25.0 - vbus) * 0.15
    eps_score = max(0.0, min(1.0, eps_score))

    # 2. TCS Health — panel_temp warn line dropped from an uncalibrated 85C
    #    to roadmap.md's real 55C engineering warn threshold, with a slope
    #    steep enough to produce a meaningful score within a 10-minute
    #    window instead of needing to approach the mission-loss line.
    #    49C (not roadmap.md's 55C) — verified directly at these exact
    #    dt=1/duration=600s settings: nominal orbital thermal cycling maxes
    #    at 47.36C with zero fault active, so 49C keeps a real 1.6C safety
    #    margin against false positives while firing early enough in a
    #    600s run to be visible live (thermal_runaway crosses this by
    #    ~step 246, not step 485+ like the original 55C/0.08 slope did).
    #    battery_temp's warn line matches engine_b.py's own recalibration
    #    (44C — the original 35C false-positives on this simulator's
    #    nominal orbital thermal cycling, verified up to 41.4C with zero
    #    fault active).
    p_temp = state.tcs.panel_temp
    b_temp = state.tcs.battery_temp

    tcs_score = 1.0
    if p_temp > 49.0:
        tcs_score -= (p_temp - 49.0) * 0.17
    elif p_temp < -10.0:
        tcs_score -= (-10.0 - p_temp) * 0.01
    if b_temp > 44.0:
        tcs_score -= (b_temp - 44.0) * 0.05
    elif b_temp < 0.0:
        tcs_score -= (0.0 - b_temp) * 0.05
    tcs_score = max(0.0, min(1.0, tcs_score))

    # 3. ADCS Health — attitude_error warn line matches roadmap.md's 5deg
    #    engineering threshold; reaction wheel matches the 5000 RPM line.
    err = state.adcs.attitude_error
    wheel = state.adcs.reaction_wheel_speed

    adcs_score = 1.0
    if abs(err) > 5.0:
        adcs_score -= (abs(err) - 5.0) * 0.05
    if abs(wheel) > 5000.0:
        adcs_score -= (abs(wheel) - 5000.0) * 0.0002
    adcs_score = max(0.0, min(1.0, adcs_score))

    # 4. TT&C Health — signal dropout below lock threshold (-90 dBm)
    sig = state.ttc.signal_strength
    ttc_score = 1.0
    if sig < -90.0:
        ttc_score -= (-90.0 - sig) * 0.05
    ttc_score = max(0.0, min(1.0, ttc_score))

    # Overall system health: mean, for display (VITALS agent page).
    system_health = (eps_score + tcs_score + adcs_score + ttc_score) / 4.0
    # Worst subsystem: for the anomaly-trigger fallback in api.py. Averaging
    # masks a single degraded subsystem (a fully-failed TCS with healthy
    # EPS/ADCS averages out to 0.67, not obviously anomalous) — the trigger
    # should react to the worst subsystem, not the mean of all.
    worst_health = min(eps_score, tcs_score, adcs_score, ttc_score)

    return {
        "eps_health": eps_score,
        "tcs_health": tcs_score,
        "adcs_health": adcs_score,
        "ttc_health": ttc_score,
        "system_health": system_health,
        "worst_health": worst_health,
    }
