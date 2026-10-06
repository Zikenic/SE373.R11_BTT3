"""CLI Demo runner for Flight Booking Agent with structured, readable terminal output.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Vạn Khải - MSSV: 24520719
"""

from __future__ import annotations
import argparse
import json
import sys
from typing import Any, Dict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from agents import FlightAgent
from flight_domain import FlightConstraints
from mock_airline import MockAirline


def print_banner(pattern: str, scenario: str, approval: bool, mode: str):
    print("=" * 70)
    print("  HỆ THỐNG AGENT ĐẶT VÉ MÁY BAY - SE373.R11 (BTVN #3)")
    print("  Sinh viên: Bùi Vạn Khải - MSSV: 24520719")
    print(f"  Pattern: {pattern.upper()} | Scenario: {scenario.upper()} | Approval: {approval} | Mode: {mode.upper()}")
    print("=" * 70)


def setup_scenario(scenario: str) -> tuple[MockAirline, FlightConstraints, bool]:
    """Configure isolated environment for the specified scenario."""
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
    approval = True

    sc_lower = scenario.lower()
    if sc_lower in ["normal", "approved", "success"]:
        approval = True
    elif sc_lower in ["awaiting_approval", "pending", "pending_review"]:
        approval = False
    elif sc_lower in ["declined", "user_declined"]:
        approval = False
    elif sc_lower in ["sold_out", "sold_out_fallback"]:
        airline.simulate_sold_out("VN101")
        approval = True
    elif sc_lower in ["no_flight", "no_matching_flights"]:
        constraints.destination = "PQC"  # Route with 0 flights
        approval = True
    elif sc_lower in ["transient_error", "retry"]:
        airline.simulate_transient_failure("search_flights", count=1)
        approval = True
    elif sc_lower in ["price_boundary", "price_exceeded"]:
        # Flight prices all above limit except boundary
        constraints.max_price_vnd = 1_500_000  # VN101 is 1.65M -> rejected
        approval = True
    else:
        print(f"[CẢNH BÁO] Không rõ kịch bản '{scenario}', sử dụng mặc định 'normal'.")

    return airline, constraints, approval


def run_demo(pattern: str, scenario: str, approval_override: str = "auto", mode: str = "deterministic"):
    airline, constraints, default_approval = setup_scenario(scenario)

    if approval_override == "yes":
        approval = True
    elif approval_override == "no":
        approval = False
    else:
        approval = default_approval

    print_banner(pattern, scenario, approval, mode)

    agent = FlightAgent(
        airline=airline,
        constraints=constraints,
        user_approved=approval,
        mode=mode,
    )

    result_state = agent.run(pattern=pattern, approval=approval)

    # Print Structured Execution Traces
    print("\n--- NHẬT KÝ THỰC THI (STRUCTURED TRACE) ---")
    traces = agent.harness.traces
    if not traces:
        print("  (Không có thao tác tool nào được phát sinh)")
    for rec in traces:
        print(f"\n[BƯỚC {rec.step_index}]")
        print(f"  Thao tác     : {rec.action} ({rec.pattern})")
        print(f"  Tool         : {rec.tool_name}")
        print(f"  Tham số      : {json.dumps(rec.tool_args, ensure_ascii=False)}")
        print(f"  Harness Check: {rec.harness_verdict}")
        if rec.message:
            print(f"  Ghi chú      : {rec.message}")
        if rec.tool_result is not None:
            res_str = json.dumps(rec.tool_result, ensure_ascii=False)
            if len(res_str) > 150:
                res_str = res_str[:147] + "..."
            print(f"  Kết quả tool : {res_str}")

    # Summary Outcome
    print("\n" + "=" * 70)
    print("--- TỔNG KẾT KẾT QUẢ ---")
    status = result_state.get("status")
    print(f"Trạng thái kết thúc : {status}")
    print(f"Tổng số bước        : {result_state.get('total_steps', agent.harness.step_counter)}")
    print(f"Tổng lượt gọi tool  : {result_state.get('total_tool_calls', agent.harness.tool_call_counter)}")
    print(f"Thời gian thực thi  : {result_state.get('runtime_sec', 0.0):.4f} giây")

    if status == "SUCCESS":
        comp = result_state.get("completion_details", {})
        print(f"[NGHIỆM THU CODE] ĐÃ XÁC NHẬN VÉ:")
        print(f"  Mã vé đặt (Booking ID): {comp.get('booking_id')}")
        print(f"  Mã chuyến bay        : {comp.get('flight_id')}")
        print(f"  Hành khách           : {comp.get('passenger_name')}")
        print(f"  Số ghế               : {comp.get('seat_number')}")
        print(f"  Giá vé               : {comp.get('price_vnd', 0):,} VND")
        print(f"  Trạng thái vé        : {comp.get('status')}")
    elif status == "PENDING_REVIEW":
        print(f"[HARNESS CHỜ DUYỆT] Thao tác dừng trước khi thực hiện ghi.")
        print(f"  Lý do                : Cần sự đồng ý của người dùng để giữ/đặt chỗ.")
        print(f"  Số lượng ghi đã chặn : {sum(1 for t in traces if t.harness_verdict == 'PERMISSION_DENIED')}")
    elif status == "HANDOFF":
        handoff = result_state.get("handoff_package", {})
        print(f"[BÀN GIAO CHO NGƯỜI DÙNG]")
        print(f"  Lý do bàn giao       : {handoff.get('reason')}")
        print(f"  Câu hỏi can thiệp    : {handoff.get('human_question')}")
        print(f"  Các chuyến đã thử    : {handoff.get('flights_attempted')}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy Demo Agent Đặt Vé Máy Bay SE373.R11")
    parser.add_argument(
        "--pattern",
        choices=["react", "plan_execute", "hybrid"],
        default="react",
        help="Mẫu thiết kế Agent",
    )
    parser.add_argument(
        "--scenario",
        choices=["normal", "awaiting_approval", "sold_out", "no_flight", "transient_error", "price_boundary"],
        default="normal",
        help="Kịch bản kiểm thử",
    )
    parser.add_argument(
        "--approval",
        choices=["auto", "yes", "no"],
        default="auto",
        help="Phê duyệt của người dùng (yes/no/auto)",
    )
    parser.add_argument(
        "--mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Chế độ chạy (deterministic: xác định local, llm: gọi LLM qua LangChain)",
    )

    args = parser.parse_args()
    run_demo(args.pattern, args.scenario, args.approval, args.mode)
