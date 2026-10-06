"""Safety Harness for Flight Reservation Agent.
Implements the 4 required harness layers and termination/safety loop detection.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Vạn Khải - MSSV: 24520719
"""

from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from flight_domain import (
    Booking,
    ExecutionStatus,
    Flight,
    FlightConstraints,
    HandoffPackage,
    HoldBooking,
    RunLimits,
    TraceRecord,
)
from mock_airline import (
    AirlineServiceUnavailableError,
    FlightNotFoundError,
    FlightSoldOutError,
    MockAirline,
    MockAirlineError,
    OwnershipViolationError,
)


# =====================================================================
# 2.1 CONSTRAINT LAYER — Constraints are DATA
# =====================================================================

class ConstraintLayer:
    """Verifies that candidate flights and reservation parameters strictly comply
    with structured requirements before any sensitive action is dispatched.
    """

    def __init__(self, constraints: FlightConstraints):
        self.constraints = constraints

    def validate_flight(self, flight: Flight) -> Tuple[bool, str]:
        """Machine-checkable policy validation on a Flight object."""
        return self.constraints.validate_flight(flight)

    def validate_hold_parameters(
        self, flight_id: str, passenger_name: str, airline: MockAirline
    ) -> Tuple[bool, str]:
        """Validate flight and passenger before holding seats."""
        if passenger_name.strip().lower() != self.constraints.passenger_name.strip().lower():
            return (
                False,
                f"Tên hành khách không khớp ràng buộc ({passenger_name} != {self.constraints.passenger_name})",
            )

        flight = airline.flights.get(flight_id)
        if not flight:
            return False, f"Chuyến bay '{flight_id}' không tồn tại trong hệ thống."

        return self.validate_flight(flight)

    def validate_confirm_parameters(
        self, hold_id: str, passenger_name: str, airline: MockAirline
    ) -> Tuple[bool, str]:
        """Validate hold and passenger before confirming reservation."""
        if passenger_name.strip().lower() != self.constraints.passenger_name.strip().lower():
            return (
                False,
                f"Tên hành khách không khớp ({passenger_name} != {self.constraints.passenger_name})",
            )

        hold = airline.holds.get(hold_id)
        if not hold:
            return False, f"Mã giữ chỗ '{hold_id}' không tồn tại."

        flight = airline.flights.get(hold.flight_id)
        if not flight:
            return False, f"Chuyến bay '{hold.flight_id}' của lệnh giữ chỗ không tồn tại."

        # Verify flight still satisfies price and route constraints
        return self.validate_flight(flight)


# =====================================================================
# 2.2 PERMISSION LAYER — Authorization & Ownership Gate
# =====================================================================

class PermissionLayer:
    """Enforces authorization gates for write/destructive actions and
    verifies passenger ownership to prevent cross-passenger tampering.
    """

    READ_TOOLS: Set[str] = {"search_flights", "get_flight_details", "get_booking_details"}
    WRITE_TOOLS: Set[str] = {"hold_booking", "confirm_booking", "cancel_hold"}

    def __init__(self, user_approved: bool = False, authorized_passenger: str = "Bui Van Khai"):
        self.user_approved = user_approved
        self.authorized_passenger = authorized_passenger

    def set_approval(self, approved: bool) -> None:
        self.user_approved = approved

    def check_permission(
        self, tool_name: str, args: Dict[str, Any], airline: MockAirline
    ) -> Tuple[bool, str]:
        """Authorize tool calls based on operation type and passenger ownership."""
        # 1. Gate write/destructive operations behind user approval
        if tool_name in self.WRITE_TOOLS:
            if not self.user_approved:
                return (
                    False,
                    f"Thao tác ghi '{tool_name}' bị từ chối: Cần người dùng phê duyệt (approval=False).",
                )

        # 2. Enforce passenger ownership on operations involving passenger name
        req_passenger = args.get("passenger_name")
        if req_passenger and req_passenger.strip().lower() != self.authorized_passenger.strip().lower():
            return (
                False,
                f"Vi phạm quyền sở hữu: Hành khách '{req_passenger}' không được phép thao tác bởi người dùng '{self.authorized_passenger}'.",
            )

        # 3. Ownership check on existing bookings
        booking_id = args.get("booking_id")
        if booking_id:
            booking = airline.bookings.get(booking_id)
            if booking and booking.passenger_name.strip().lower() != self.authorized_passenger.strip().lower():
                return (
                    False,
                    f"Vi phạm quyền sở hữu: Booking '{booking_id}' thuộc về '{booking.passenger_name}', không phải '{self.authorized_passenger}'.",
                )

        # 4. Ownership check on existing holds
        hold_id = args.get("hold_id")
        if hold_id:
            hold = airline.holds.get(hold_id)
            if hold and hold.passenger_name.strip().lower() != self.authorized_passenger.strip().lower():
                return (
                    False,
                    f"Vi phạm quyền sở hữu: Giữ chỗ '{hold_id}' thuộc về '{hold.passenger_name}', không phải '{self.authorized_passenger}'.",
                )

        return True, "Hợp lệ"


# =====================================================================
# 2.3 COMPLETION LAYER — Completion checked by CODE
# =====================================================================

class CompletionLayer:
    """Predicate inspecting actual mock airline state to verify successful completion.
    The task is NEVER considered done based solely on model output statements.
    """

    def __init__(self, constraints: FlightConstraints):
        self.constraints = constraints

    def verify_completion(
        self, booking_id: Optional[str], airline: MockAirline
    ) -> Tuple[bool, Dict[str, Any]]:
        """Strict machine-checkable verification against the airline database."""
        if not booking_id:
            return False, {"reason": "Chưa có mã đặt vé (booking_id is None)"}

        booking = airline.bookings.get(booking_id)
        if not booking:
            return False, {"reason": f"Không tìm thấy booking '{booking_id}' trong cơ sở dữ liệu"}

        # 1. Must be confirmed
        if booking.status != "confirmed":
            return False, {
                "reason": f"Booking '{booking_id}' chưa ở trạng thái 'confirmed' (hiện tại: {booking.status})"
            }

        # 2. Passenger must match
        if booking.passenger_name.strip().lower() != self.constraints.passenger_name.strip().lower():
            return False, {
                "reason": f"Tên trên vé '{booking.passenger_name}' không đúng với yêu cầu '{self.constraints.passenger_name}'"
            }

        # 3. Flight must exist
        flight = airline.flights.get(booking.flight_id)
        if not flight:
            return False, {"reason": f"Chuyến bay '{booking.flight_id}' trên vé không tồn tại"}

        # 4. Flight must satisfy all constraints
        is_ok, reason = self.constraints.validate_flight(flight)
        if not is_ok:
            return False, {"reason": f"Chuyến bay trên vé vi phạm ràng buộc: {reason}"}

        # 5. Price limit check
        if booking.price_vnd > self.constraints.max_price_vnd:
            return False, {
                "reason": f"Giá vé thanh toán {booking.price_vnd:,} VND vượt hạn mức {self.constraints.max_price_vnd:,} VND"
            }

        return True, {
            "booking_id": booking.booking_id,
            "flight_id": booking.flight_id,
            "passenger_name": booking.passenger_name,
            "seat_number": booking.seat_number,
            "price_vnd": booking.price_vnd,
            "status": booking.status,
            "message": "Nghiệm thu hoàn tất: Vé đã được xác nhận và thỏa mãn toàn bộ ràng buộc.",
        }


# =====================================================================
# 2.4 HANDOFF LAYER — Structured Human Intervention
# =====================================================================

class HandoffLayer:
    """Constructs structured handoff packages with complete diagnostic traces
    so a human can resolve the situation without reviewing source code.
    """

    @staticmethod
    def create_handoff(
        status: ExecutionStatus,
        reason: str,
        human_question: str,
        actions_attempted: List[str],
        flights_attempted: List[str],
        traces: List[TraceRecord],
        booking_id: Optional[str] = None,
        hold_id: Optional[str] = None,
    ) -> HandoffPackage:
        trace_summary = [
            {
                "step": t.step_index,
                "tool": t.tool_name,
                "verdict": t.harness_verdict,
                "action": t.action,
            }
            for t in traces
        ]
        return HandoffPackage(
            status=status,
            reason=reason,
            actions_attempted=actions_attempted,
            flights_attempted=flights_attempted,
            booking_id=booking_id,
            hold_id=hold_id,
            trace_summary=trace_summary,
            human_question=human_question,
        )


# =====================================================================
# 3. SAFETY HARNESS & TERMINATION / LOOP DETECTION
# =====================================================================

class FlightHarness:
    """Central gateway between Agent decision-making and mock airline tools.
    Integrates all 4 layers, enforces safety limits, detects infinite loops,
    and handles transient retries.
    """

    def __init__(
        self,
        constraints: FlightConstraints,
        user_approved: bool = False,
        limits: Optional[RunLimits] = None,
    ):
        self.constraints = constraints
        self.limits = limits or RunLimits()
        self.constraint_layer = ConstraintLayer(constraints)
        self.permission_layer = PermissionLayer(
            user_approved=user_approved,
            authorized_passenger=constraints.passenger_name,
        )
        self.completion_layer = CompletionLayer(constraints)
        self.handoff_layer = HandoffLayer()

        # State tracking
        self.traces: List[TraceRecord] = []
        self.actions_attempted: List[str] = []
        self.flights_attempted: List[str] = []
        self.action_history: List[str] = []
        self.step_counter: int = 0
        self.tool_call_counter: int = 0
        self.start_time: float = time.time()
        self.consecutive_stalls: int = 0
        self.last_state_signature: str = ""

    def reset(self, user_approved: bool = False) -> None:
        """Reset harness state for fresh benchmark executions."""
        self.permission_layer.set_approval(user_approved)
        self.traces.clear()
        self.actions_attempted.clear()
        self.flights_attempted.clear()
        self.action_history.clear()
        self.step_counter = 0
        self.tool_call_counter = 0
        self.start_time = time.time()
        self.consecutive_stalls = 0
        self.last_state_signature = ""

    def check_safety_limits(self) -> Tuple[bool, Optional[ExecutionStatus], str]:
        """Check hard safety boundaries (max steps, tool calls, runtime)."""
        elapsed = time.time() - self.start_time
        if elapsed > self.limits.max_runtime_sec:
            return (
                False,
                ExecutionStatus.LIMIT_EXCEEDED,
                f"Quá thời gian thực thi tối đa ({elapsed:.1f}s > {self.limits.max_runtime_sec}s)",
            )
        if self.step_counter >= self.limits.max_steps:
            return (
                False,
                ExecutionStatus.LIMIT_EXCEEDED,
                f"Vượt quá số bước tối đa ({self.step_counter} >= {self.limits.max_steps})",
            )
        if self.tool_call_counter >= self.limits.max_tool_calls:
            return (
                False,
                ExecutionStatus.LIMIT_EXCEEDED,
                f"Vượt quá số lượt gọi tool tối đa ({self.tool_call_counter} >= {self.limits.max_tool_calls})",
            )
        return True, None, "Limits OK"

    def detect_loop(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """Detect infinite execution loops:
        1. Repeated identical (tool, args) calls
        2. Repeated failures on the same action
        3. Stalled progress across multiple iterations
        """
        # Canonical string representation of action
        args_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        action_sig = f"{tool_name}::{args_key}"

        # 1. Repeated identical action
        recent_window = self.action_history[-self.limits.max_repeated_actions :]
        if len(recent_window) >= self.limits.max_repeated_actions and all(
            a == action_sig for a in recent_window
        ):
            return True, f"Phát hiện lặp vô hạn: Thao tác '{action_sig}' bị lặp lại {self.limits.max_repeated_actions} lần liên tiếp."

        # 2. Stalled progress: too many steps without discovering or holding candidates
        if self.consecutive_stalls >= 4:
            return True, f"Phát hiện đình trệ (stalled progress): {self.consecutive_stalls} bước không tạo ra tiến triển mới."

        return False, "No loop"

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        airline: MockAirline,
        tools_dict: Dict[str, Any],
        pattern: str = "ReAct",
    ) -> Tuple[bool, Any, str]:
        """Intercept, validate, execute, and monitor every tool call."""
        self.step_counter += 1
        self.actions_attempted.append(tool_name)

        flight_id = args.get("flight_id")
        if flight_id and flight_id not in self.flights_attempted:
            self.flights_attempted.append(flight_id)

        # 1. Hard limits check
        limits_ok, limit_status, limit_msg = self.check_safety_limits()
        if not limits_ok:
            rec = TraceRecord(
                step_index=self.step_counter,
                pattern=pattern,
                action=tool_name,
                tool_name=tool_name,
                tool_args=args,
                harness_verdict="REJECT_LIMIT_EXCEEDED",
                message=limit_msg,
            )
            self.traces.append(rec)
            return False, {"error": limit_msg, "status": limit_status}, limit_msg

        # 2. Loop detection check
        is_loop, loop_msg = self.detect_loop(tool_name, args)
        if is_loop:
            rec = TraceRecord(
                step_index=self.step_counter,
                pattern=pattern,
                action=tool_name,
                tool_name=tool_name,
                tool_args=args,
                harness_verdict="REJECT_LOOP_DETECTED",
                message=loop_msg,
            )
            self.traces.append(rec)
            return False, {"error": loop_msg, "status": ExecutionStatus.LOOP_DETECTED}, loop_msg

        args_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        self.action_history.append(f"{tool_name}::{args_key}")

        # 3. Permission Layer Check
        perm_ok, perm_msg = self.permission_layer.check_permission(tool_name, args, airline)
        if not perm_ok:
            rec = TraceRecord(
                step_index=self.step_counter,
                pattern=pattern,
                action=tool_name,
                tool_name=tool_name,
                tool_args=args,
                harness_verdict="PERMISSION_DENIED",
                message=perm_msg,
            )
            self.traces.append(rec)
            return False, {"error": perm_msg, "type": "PermissionDenied"}, perm_msg

        # 4. Constraint Layer Check before sensitive write actions
        if tool_name == "hold_booking":
            c_ok, c_msg = self.constraint_layer.validate_hold_parameters(
                flight_id=args["flight_id"],
                passenger_name=args["passenger_name"],
                airline=airline,
            )
            if not c_ok:
                rec = TraceRecord(
                    step_index=self.step_counter,
                    pattern=pattern,
                    action=tool_name,
                    tool_name=tool_name,
                    tool_args=args,
                    harness_verdict="CONSTRAINT_VIOLATION",
                    message=c_msg,
                )
                self.traces.append(rec)
                return False, {"error": c_msg, "type": "ConstraintViolation"}, c_msg

        elif tool_name == "confirm_booking":
            c_ok, c_msg = self.constraint_layer.validate_confirm_parameters(
                hold_id=args["hold_id"],
                passenger_name=args["passenger_name"],
                airline=airline,
            )
            if not c_ok:
                rec = TraceRecord(
                    step_index=self.step_counter,
                    pattern=pattern,
                    action=tool_name,
                    tool_name=tool_name,
                    tool_args=args,
                    harness_verdict="CONSTRAINT_VIOLATION",
                    message=c_msg,
                )
                self.traces.append(rec)
                return False, {"error": c_msg, "type": "ConstraintViolation"}, c_msg

        # 5. Dispatch Tool with Transient Retry Handling
        target_tool = tools_dict.get(tool_name)
        if not target_tool:
            err = f"Tool '{tool_name}' không tồn tại trong danh mục."
            rec = TraceRecord(
                step_index=self.step_counter,
                pattern=pattern,
                action=tool_name,
                tool_name=tool_name,
                tool_args=args,
                harness_verdict="TOOL_NOT_FOUND",
                message=err,
            )
            self.traces.append(rec)
            return False, {"error": err}, err

        retries = 0
        last_error = None
        while retries <= self.limits.max_retries:
            self.tool_call_counter += 1
            try:
                # Invoke tool through LangChain tool interface
                result = target_tool.invoke(args)
                self.consecutive_stalls = 0  # Successful progress reset

                rec = TraceRecord(
                    step_index=self.step_counter,
                    pattern=pattern,
                    action=tool_name,
                    tool_name=tool_name,
                    tool_args=args,
                    tool_result=result,
                    harness_verdict="PASS",
                    message=f"Thực thi thành công (lần gọi {self.tool_call_counter})"
                    + (f" sau {retries} lần thử lại" if retries > 0 else ""),
                )
                self.traces.append(rec)
                return True, result, "Success"

            except AirlineServiceUnavailableError as exc:
                last_error = exc
                retries += 1
                if retries <= self.limits.max_retries:
                    time.sleep(0.05)  # brief backoff
                    continue
                else:
                    break

            except (FlightSoldOutError, MockAirlineError, Exception) as exc:
                last_error = exc
                break

        # Execution failed
        self.consecutive_stalls += 1
        fail_msg = f"{type(last_error).__name__}: {str(last_error)}"
        rec = TraceRecord(
            step_index=self.step_counter,
            pattern=pattern,
            action=tool_name,
            tool_name=tool_name,
            tool_args=args,
            tool_result=None,
            harness_verdict="EXECUTION_ERROR",
            message=fail_msg,
        )
        self.traces.append(rec)
        return False, {"error": fail_msg, "type": type(last_error).__name__}, fail_msg
