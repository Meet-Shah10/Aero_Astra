def calculate_vitals(state) -> dict:
    """
    Computes heuristic health scores (0.0 to 1.0) for satellite subsystems.
    """
    # 1. EPS Health
    soc = state.eps.battery_soc
    vbus = state.eps.bus_voltage
    
    eps_score = 1.0
    if soc < 0.4:
        eps_score -= (0.4 - soc) * 2.0
    
    if vbus < 28.0:
        eps_score -= (28.0 - vbus) * 0.1
    elif vbus > 32.0:
        eps_score -= (vbus - 32.0) * 0.1

    if state.active_fault == "eps_battery_degradation":
        eps_score -= 0.4 * state.fault_severity
    elif state.active_fault == "eps_cascade_power_failure":
        eps_score -= state.fault_severity
        
    eps_score = max(0.0, min(1.0, eps_score))
    
    # 2. TCS Health
    p_temp = state.tcs.panel_temp
    b_temp = state.tcs.battery_temp
    
    tcs_score = 1.0
    if b_temp > 40.0:
        tcs_score -= (b_temp - 40.0) * 0.05
    elif b_temp < 0.0:
        tcs_score -= (0.0 - b_temp) * 0.05
        
    if p_temp > 85.0:
        tcs_score -= (p_temp - 85.0) * 0.01
    elif p_temp < -40.0:
        tcs_score -= (-40.0 - p_temp) * 0.01

    if state.active_fault == "eps_cascade_power_failure":
        tcs_score -= 0.5 * state.fault_severity
        
    tcs_score = max(0.0, min(1.0, tcs_score))
    
    # 3. ADCS Health
    err = state.adcs.attitude_error
    wheel = state.adcs.reaction_wheel_speed
    
    adcs_score = 1.0
    if abs(err) > 2.0:
        adcs_score -= (abs(err) - 2.0) * 0.1
    if abs(wheel) > 6000.0:
        adcs_score -= (abs(wheel) - 6000.0) * 0.0001
        
    adcs_score = max(0.0, min(1.0, adcs_score))
    
    # Overall System Health
    system_health = (eps_score + tcs_score + adcs_score) / 3.0
    
    return {
        "eps_health": eps_score,
        "tcs_health": tcs_score,
        "adcs_health": adcs_score,
        "system_health": system_health
    }
