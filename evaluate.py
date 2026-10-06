"""Benchmark Evaluation Suite for SE373.R11 Flight Booking Agent.
Evaluates ReAct, Plan-then-Execute, and Hybrid across reproducible test scenarios.
Collects and dumps results to results/benchmark.json and results/benchmark.jsonl.

SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Văn Khải - MSSV: 24520719
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from agents import FlightAgent
from flight_domain import ExecutionStatus, FlightConstraints
from mock_airline import MockAirline


# =====================================================================
# Benchmark Scenario Definitions
# =====================================================================

SCENARIOS = [
    {
        "id": "approved",
        "name": "1. Đặt vé bình thường (Có phê duyệt)",
        "approval": True,
        "setup": lambda airline, constraints: None,
        "expected": {
            "react": ExecutionStatus.SUCCESS,
            "plan_execute": ExecutionStatus.SUCCESS,
            "hybrid": ExecutionStatus.SUCCESS,
        },
    },
    {
        "id": "awaiting_approval",
        "name": "2. Tìm thấy chuyến nhưng chờ phê duyệt",
        "approval": False,
        "setup": lambda airline, constraints: None,
        "expected": {
            "react": ExecutionStatus.PENDING_REVIEW,
            "plan_execute": ExecutionStatus.PENDING_REVIEW,
            "hybrid": ExecutionStatus.PENDING_REVIEW,
        },
    },
    {
        "id": "declined",
        "name": "3. Người dùng từ chối đặt vé",
        "approval": False,
        "setup": lambda airline, constraints: None,
        "expected": {
            "react": ExecutionStatus.PENDING_REVIEW,
            "plan_execute": ExecutionStatus.PENDING_REVIEW,
            "hybrid": ExecutionStatus.PENDING_REVIEW,
        },
    },
    {
        "id": "sold_out_fallback",
        "name": "4. Chuyến bay ưu tiên VN101 bị hết chỗ (SOLD_OUT)",
        "approval": True,
        "setup": lambda airline, constraints: airline.simulate_sold_out("VN101"),
        "expected": {
            "react": ExecutionStatus.SUCCESS,      # Phục hồi sang chuyến dự phòng VN102
            "plan_execute": ExecutionStatus.HANDOFF, # Kế hoạch tĩnh dừng và bàn giao
            "hybrid": ExecutionStatus.SUCCESS,     # Tái lập kế hoạch tức thời sang VN102
        },
    },
    {
        "id": "no_flight",
        "name": "5. Không có chuyến bay phù hợp",
        "approval": True,
        "setup": lambda airline, constraints: setattr(constraints, "destination", "PQC"),
        "expected": {
            "react": ExecutionStatus.HANDOFF,
            "plan_execute": ExecutionStatus.HANDOFF,
            "hybrid": ExecutionStatus.HANDOFF,
        },
    },
    {
        "id": "transient_error",
        "name": "6. Lỗi dịch vụ tìm kiếm tạm thời (Thử lại thành công)",
        "approval": True,
        "setup": lambda airline, constraints: airline.simulate_transient_failure("search_flights", count=1),
        "expected": {
            "react": ExecutionStatus.SUCCESS,
            "plan_execute": ExecutionStatus.SUCCESS,
            "hybrid": ExecutionStatus.SUCCESS,
        },
    },
    {
        "id": "price_boundary",
        "name": "7. Giá vé vượt hạn mức ngân sách (Ranh giới giá)",
        "approval": True,
        "setup": lambda airline, constraints: setattr(constraints, "max_price_vnd", 1_200_000),
        "expected": {
            "react": ExecutionStatus.HANDOFF,
            "plan_execute": ExecutionStatus.HANDOFF,
            "hybrid": ExecutionStatus.HANDOFF,
        },
    },
]

PATTERNS = ["react", "plan_execute", "hybrid"]


def run_benchmark(output_dir: str = "results", mode: str = "deterministic") -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "benchmark.json")
    jsonl_path = os.path.join(output_dir, "benchmark.jsonl")

    records: List[Dict[str, Any]] = []

    print("\n" + "=" * 80)
    print("  KHỞI CHẠY BENCHMARK ĐÁNH GIÁ 3 KIẾN TRÚC AGENT - SE373.R11")
    print("  Sinh viên: Bùi Văn Khải - MSSV: 24520719")
    print(f"  Chế độ: {mode.upper()} | Tổng kịch bản: {len(SCENARIOS)} | Tổng lượt chạy: {len(SCENARIOS) * len(PATTERNS)}")
    print("=" * 80)

    for sc in SCENARIOS:
        sc_id = sc["id"]
        sc_name = sc["name"]
        print(f"\n[KỊCH BẢN] {sc_name}")

        for pat in PATTERNS:
            # Fresh state for each run
            airline = MockAirline()
            constraints = FlightConstraints(
                origin="SGN",
                destination="DAD",
                passenger_name="Bui Van Khai",
                date_min="2026-10-01",
                date_max="2026-10-31",
                reference_date="2026-10-06",
                latest_departure_time="12:00",
                max_price_vnd=2_000_000,
            )
            sc["setup"](airline, constraints)

            agent = FlightAgent(
                airline=airline,
                constraints=constraints,
                user_approved=sc["approval"],
                mode=mode,
            )

            t0 = time.time()
            res = agent.run(pattern=pat, approval=sc["approval"])
            elapsed_ms = (time.time() - t0) * 1000

            actual_status = res.get("status")
            expected_status = sc["expected"][pat]
            status_match = actual_status == expected_status

            write_tools_called = sum(
                1 for t in agent.harness.traces
                if t.tool_name in ["hold_booking", "confirm_booking", "cancel_hold"]
                and t.harness_verdict == "PASS"
            )

            booking_id = res.get("current_booking_id")
            flight_id = None
            if booking_id and booking_id in airline.bookings:
                flight_id = airline.bookings[booking_id].flight_id

            completion_passed = False
            if booking_id:
                completion_passed, _ = agent.harness.completion_layer.verify_completion(
                    booking_id, airline
                )

            record = {
                "scenario_id": sc_id,
                "scenario_name": sc_name,
                "pattern": pat,
                "mode": mode,
                "expected_status": expected_status.value if hasattr(expected_status, "value") else expected_status,
                "actual_status": actual_status.value if hasattr(actual_status, "value") else str(actual_status),
                "status_match": status_match,
                "completion_gate_passed": completion_passed,
                "controller_steps": agent.harness.step_counter,
                "tool_calls": agent.harness.tool_call_counter,
                "write_tools_called": write_tools_called,
                "runtime_ms": round(elapsed_ms, 2),
                "booking_id": booking_id,
                "flight_id": flight_id,
                "traces_count": len(agent.harness.traces),
            }
            records.append(record)

            status_icon = "✔ PASS" if status_match else "✘ FAIL"
            print(
                f"  {pat:14} -> {str(actual_status):14} "
                f"(Kỳ vọng: {str(expected_status):14}) | "
                f"Steps: {agent.harness.step_counter:2} | "
                f"Tools: {agent.harness.tool_call_counter:2} | "
                f"Time: {elapsed_ms:6.2f}ms | {status_icon}"
            )

    # Save to JSON and JSONL
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary Aggregation Table
    summary = {}
    for pat in PATTERNS:
        pat_records = [r for r in records if r["pattern"] == pat]
        total = len(pat_records)
        passed = sum(1 for r in pat_records if r["status_match"])
        success_count = sum(1 for r in pat_records if r["actual_status"] == "SUCCESS")
        pending_count = sum(1 for r in pat_records if r["actual_status"] == "PENDING_REVIEW")
        handoff_count = sum(1 for r in pat_records if r["actual_status"] == "HANDOFF")
        avg_steps = sum(r["controller_steps"] for r in pat_records) / total
        avg_tools = sum(r["tool_calls"] for r in pat_records) / total
        avg_ms = sum(r["runtime_ms"] for r in pat_records) / total

        summary[pat] = {
            "total_runs": total,
            "passed": passed,
            "success_count": success_count,
            "pending_count": pending_count,
            "handoff_count": handoff_count,
            "avg_steps": round(avg_steps, 2),
            "avg_tools": round(avg_tools, 2),
            "avg_ms": round(avg_ms, 2),
        }

    print("\n" + "=" * 80)
    print("  BẢNG TỔNG HỢP SO SÁNH BA MẪU THIẾT KẾ (BENCHMARK SUMMARY)")
    print("=" * 80)
    print(f"{'Mẫu thiết kế':<18} | {'Khớp/Tổng':<10} | {'SUCCESS':<8} | {'PENDING':<8} | {'HANDOFF':<8} | {'Tool TB':<8} | {'Bước TB':<8} | {'Thời gian TB'}")
    print("-" * 80)
    for pat in PATTERNS:
        s = summary[pat]
        print(
            f"{pat:<18} | {s['passed']}/{s['total_runs']:<8} | {s['success_count']:<8} | "
            f"{s['pending_count']:<8} | {s['handoff_count']:<8} | {s['avg_tools']:<8} | "
            f"{s['avg_steps']:<8} | {s['avg_ms']:.2f} ms"
        )
    print("=" * 80)
    print(f"\nKết quả chi tiết đã được lưu tại:\n  - {json_path}\n  - {jsonl_path}\n")

    return {"summary": summary, "records": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy Benchmark So Sánh 3 Kiến Trúc Agent")
    parser.add_argument("--output-dir", default="results", help="Thư mục lưu kết quả")
    parser.add_argument(
        "--mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Chế độ chạy đánh giá",
    )
    args = parser.parse_args()
    run_benchmark(output_dir=args.output_dir, mode=args.mode)
