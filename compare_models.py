import time
import os
import json
import asyncio
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import AnomalyEvent, SeverityLevel
from backend.athena.agent import AthenaAgent
from backend.athena.schemas import AthenaContext
from backend.llm_client import build_clients, LLMProvider
from openai import OpenAI

# We will patch build_clients to force a specific model on Ollama
original_build_clients = build_clients

def run_comparison():
    models = ["mistral-nemo:12b", "llama3.2:3b"]
    
    event = AnomalyEvent(
        event_id="TEST-001",
        timestamp="2024-01-01T00:00:00Z",
        affected_subsystem="TCS",
        severity=SeverityLevel.HIGH,
        triggering_engine="engine_b",
        telemetry_snapshot={
            "tcs": {"panel_temp": 85.0, "battery_temp": 45.0},
            "eps": {"battery_soc": 0.4, "bus_voltage": 27.5, "eps_load": 0.9}
        },
        historical_context=[]
    )
    
    context = AthenaContext(
        fault_id="tcs_thermal_runaway",
        subsystem="TCS",
        severity="HIGH",
        telemetry_snapshot={"tcs_temp": 85.0},
        oracle_actions=[{"action": "Throttle CPU", "score": 0.8}, {"action": "Shed Load", "score": 0.9}],
        sherlock_diagnosis={"root_cause": "Heat Pipe Failure", "causal_chain": ["TCS", "EPS"]}
    )

    results = {}
    
    for model in models:
        print(f"\n--- Testing Model: {model} ---")
        os.environ["OLLAMA_MODEL"] = model
        
        # Instantiate agents (they will read OLLAMA_MODEL)
        sherlock = SherlockAgent()
        athena = AthenaAgent()
        
        print("Running SHERLOCK Diagnosis...")
        t0 = time.time()
        try:
            diagnosis = sherlock.diagnose(event)
            s_time = time.time() - t0
            s_res = diagnosis.model_dump()
            print(f"SHERLOCK: Success in {s_time:.2f}s")
        except Exception as e:
            s_time = time.time() - t0
            s_res = f"Error: {e}"
            print(f"SHERLOCK: Failed in {s_time:.2f}s")

        print("Running ATHENA Planning...")
        t0 = time.time()
        try:
            plan = athena.generate_plan(context)
            a_time = time.time() - t0
            a_res = plan.model_dump()
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
