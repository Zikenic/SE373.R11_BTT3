"""Run actual LLM evaluation on key scenarios and save results.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Văn Khải - MSSV: 24520719
"""

import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agents import FlightAgent
from flight_domain import FlightConstraints
from mock_airline import MockAirline


def run_llm_evaluation():
    print("=" * 70)
    print("  ĐÁNH GIÁ THỰC TẾ TRÊN MÔ HÌNH LLM (GEMINI 3.8 FLASH VIA LANGCHAIN)")
    print("=" * 70)

    patterns = ["react", "plan_execute", "hybrid"]
    results = []

    for pat in patterns:
        airline = MockAirline()
        constraints = FlightConstraints(passenger_name="Bui Van Khai")
        agent = FlightAgent(airline=airline, constraints=constraints, user_approved=True, mode="llm")

        t0 = time.time()
        res = agent.run(pattern=pat, approval=True)
        dur = time.time() - t0

        tokens = res.get("token_usage", {})
        status = res.get("status")
        comp = res.get("completion_details") or {}

        item = {
            "pattern": pat,
            "status": str(status),
            "booking_id": comp.get("booking_id"),
            "flight_id": comp.get("flight_id"),
            "steps": res.get("total_steps"),
            "tool_calls": res.get("total_tool_calls"),
            "runtime_sec": round(dur, 2),
            "token_usage": tokens,
        }
        results.append(item)
        print(f"[{pat.upper()}] Status: {status} | Booking: {comp.get('booking_id')} ({comp.get('flight_id')}) | Steps: {res.get('total_steps')} | Tools: {res.get('total_tool_calls')} | Time: {dur:.2f}s | Tokens: {tokens}")

    os.makedirs("results", exist_ok=True)
    with open("results/llm_benchmark.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\nKết quả đã lưu vào results/llm_benchmark.json")


if __name__ == "__main__":
    run_llm_evaluation()
