import time
import os
import json
import asyncio
from datetime import datetime
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import AnomalyEvent, SeverityLevel, UrgencyLevel, SherlockDiagnosis
from backend.athena.agent import AthenaAgent
from backend.athena.schemas import MissionConstraints
from backend.oracle.schemas import OracleResponse, ActionResult
from backend.simulator.schemas import MonteCarloResult

def run_comparison():
    models = ["mistral-nemo:12b", "llama3.2:3b"]
    
    event = AnomalyEvent(
        anomaly_id="TEST-001",
        flagged_subsystem="TCS",
        flagged_parameter="tcs_temp",
        severity=SeverityLevel.HIGH,
        confidence_score=0.9,
        timestamp=datetime.now(),
        telemetry_window=[
            {"tcs_temp": 85.0, "battery_temp": 45.0, "battery_soc": 0.4, "bus_voltage": 27.5, "eps_load": 0.9}
        ],
        event_log_context="TCS temp rising rapidly"
    )

    diagnosis_mock = SherlockDiagnosis(
        primary_root_cause="TCS",
        causal_chain=["TCS", "EPS"],
        affected_subsystems=["TCS", "EPS"],
        confidence_score=0.85,
        urgency=UrgencyLevel.HIGH,
        time_to_critical_estimate_minutes=10,
        reasoning="Temp is high, affecting EPS",
        graph_candidate_set=["TCS", "EPS", "ADCS", "OBC"],
        llm_attempts=1,
        diagnosis_timestamp=datetime.now()
    )

    mc1 = MonteCarloResult(
        proposed_action="tcs_throttle",
        n_runs=100,
        steps=300,
        nominal_recovery_rate=0.9,
        degraded_operation_rate=0.1,
        mission_loss_rate=0.0,
        mean_final_battery_soc=0.5,
        mean_final_attitude_error=0.1,
        std_final_battery_soc=0.05,
        outcome_counts={"nominal_recovery": 90, "degraded_operation": 10, "mission_loss": 0}
    )

    mc2 = MonteCarloResult(
        proposed_action="eps_load_shed",
        n_runs=100,
        steps=300,
        nominal_recovery_rate=0.7,
        degraded_operation_rate=0.3,
        mission_loss_rate=0.0,
        mean_final_battery_soc=0.6,
        mean_final_attitude_error=0.2,
        std_final_battery_soc=0.1,
        outcome_counts={"nominal_recovery": 70, "degraded_operation": 30, "mission_loss": 0}
    )

    oracle_mock = OracleResponse(
        fault_name="TCS",
        mode="ranking",
        results=[
            ActionResult(action_name="Throttle TCS", mc_result=mc1, safety_score=0.8, flags=[]),
            ActionResult(action_name="Shed Load EPS", mc_result=mc2, safety_score=0.6, flags=[])
        ],
        best_action="Throttle TCS",
        generated_at=time.time()
    )

    constraints = MissionConstraints(notes="Testing comparison")

    results = {}
    
    for model in models:
        print(f"\n--- Testing Model: {model} ---")
        os.environ["OLLAMA_MODEL"] = model
        
        # Instantiate agents (they will read OLLAMA_MODEL)
        sherlock = SherlockAgent()
        athena = AthenaAgent()
        
        print(f"Running SHERLOCK Diagnosis with {model}...")
        t0 = time.time()
        try:
            diagnosis = sherlock.diagnose(event)
            s_time = time.time() - t0
            s_res = diagnosis.model_dump()
            # Convert datetime to string
            s_res['diagnosis_timestamp'] = str(s_res['diagnosis_timestamp'])
            print(f"SHERLOCK: Success in {s_time:.2f}s")
        except Exception as e:
            s_time = time.time() - t0
            s_res = f"Error: {e}"
            print(f"SHERLOCK: Failed in {s_time:.2f}s")

        print(f"Running ATHENA Planning with {model}...")
        t0 = time.time()
        try:
            plan = athena.plan(
                sherlock_diagnosis=diagnosis_mock,
                oracle_response=oracle_mock,
                constraints=constraints
            )
            a_time = time.time() - t0
            a_res = plan.model_dump()
            a_res['generated_at'] = str(a_res['generated_at'])
            print(f"ATHENA: Success in {a_time:.2f}s")
        except Exception as e:
            a_time = time.time() - t0
            a_res = f"Error: {e}"
            print(f"ATHENA: Failed in {a_time:.2f}s")
            
        results[model] = {
            "sherlock_time": s_time,
            "sherlock_result": s_res,
            "athena_time": a_time,
            "athena_result": a_res
        }
        
    return results

if __name__ == "__main__":
    res = run_comparison()
    with open("model_comparison_results.json", "w") as f:
        json.dump(res, f, indent=2)
    print("\nComparison complete. Wrote model_comparison_results.json")
