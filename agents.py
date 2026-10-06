"""Three Agent Design Patterns using LangChain and LangGraph StateGraph.
1. ReAct (Reason -> Act -> Observe)
2. Plan-then-Execute (Upfront Structured Planning -> Validation -> Sequential Execution)
3. Hybrid (Strategic Planning + Environmental Monitoring + Dynamic Replanning)

SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Văn Khải - MSSV: 24520719
"""

from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, List, Optional, TypedDict
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from flight_domain import (
    ExecutionStatus,
    FlightConstraints,
    HandoffPackage,
    RunLimits,
    TraceRecord,
)
from harness import FlightHarness
from mock_airline import MockAirline
from mock_tools import create_airline_tools


# =====================================================================
# State Definition for LangGraph StateGraph
# =====================================================================

class AgentState(TypedDict, total=False):
    # Requirements & Constraints
    goal: str
    passenger_name: str
    origin: str
    destination: str
    date: Optional[str]
    user_approved: bool

    # Planning & Reasoning State
    pattern: str
    plan: List[Dict[str, Any]]
    current_step_index: int
    last_thought: str

    # Context & Discovered Data
    candidate_flights: List[Dict[str, Any]]
    selected_flight_id: Optional[str]
    backup_flight_id: Optional[str]
    current_hold_id: Optional[str]
    current_booking_id: Optional[str]

    # Tool Execution State
    next_tool_name: Optional[str]
    next_tool_args: Optional[Dict[str, Any]]
    last_tool_result: Optional[Any]
    last_error: Optional[str]

    # Termination & Diagnostics
    status: ExecutionStatus
    handoff_package: Optional[Dict[str, Any]]
    completion_details: Optional[Dict[str, Any]]
    token_usage: Dict[str, int]
    runtime_sec: float
    total_steps: int
    total_tool_calls: int


# =====================================================================
# Helper to Initialize Model from .env
# =====================================================================

def get_llm(timeout: int = 15) -> Optional[ChatOpenAI]:
    """Load model configuration safely from environment variables without exposing secrets."""
    load_dotenv()
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    model_raw = os.getenv("OPENAI_MODEL") or os.getenv("FAST_LLM", "ag/gemini-3.8-flash")
    model_name = model_raw.split(":", 1)[-1] if ":" in model_raw else model_raw

    if not api_key:
        return None

    try:
        return ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            temperature=0.0,
            timeout=timeout,
        )
    except Exception:
        return None


# =====================================================================
# Flight Agent Controller (encapsulating all 3 architectures)
# =====================================================================

class FlightAgent:
    """Manages execution for ReAct, Plan-then-Execute, and Hybrid patterns."""

    def __init__(
        self,
        airline: MockAirline,
        constraints: FlightConstraints,
        user_approved: bool = False,
        mode: str = "deterministic",  # "llm" or "deterministic"
        limits: Optional[RunLimits] = None,
    ):
        self.airline = airline
        self.constraints = constraints
        self.user_approved = user_approved
        self.mode = mode
        self.harness = FlightHarness(
            constraints=constraints,
            user_approved=user_approved,
            limits=limits or RunLimits(),
        )
        self.tools = create_airline_tools(airline)
        self.tools_dict = {t.name: t for t in self.tools}
        self.llm = get_llm() if mode == "llm" else None

    # -----------------------------------------------------------------
    # PATTERN 1: ReAct Architecture
    # -----------------------------------------------------------------

    def _build_react_graph(self) -> StateGraph:
        workflow = StateGraph(AgentState)

        def react_reason_node(state: AgentState) -> AgentState:
            state["total_steps"] = state.get("total_steps", 0) + 1
            candidates = state.get("candidate_flights", [])
            selected = state.get("selected_flight_id")
            hold_id = state.get("current_hold_id")
            booking_id = state.get("current_booking_id")
            last_err = state.get("last_error")

            # LLM Prompting if mode is LLM
            if self.mode == "llm" and self.llm:
                try:
                    sys_prompt = (
                        f"Bạn là Agent hỗ trợ đặt vé máy bay cho hành khách {self.constraints.passenger_name}. "
                        f"Nhiệm vụ: Chặng {self.constraints.origin} -> {self.constraints.destination}, "
                        f"trước {self.constraints.latest_departure_time}, giá <= {self.constraints.max_price_vnd:,} VND. "
                        f"Phê duyệt của khách: {state.get('user_approved', False)}. "
                        "Trả lời suy nghĩ ngắn gọn và chọn bước tiếp theo."
                    )
                    resp = self.llm.invoke([
                        SystemMessage(content=sys_prompt),
                        HumanMessage(content=f"Hiện tại: candidates={len(candidates)}, selected={selected}, hold={hold_id}, err={last_err}"),
                    ])
                    state["last_thought"] = str(resp.content)[:200]
                    # Track token usage if reported
                    usage = getattr(resp, "response_metadata", {}).get("token_usage", {})
                    if usage:
                        curr_usage = state.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                        curr_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                        curr_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                        curr_usage["total_tokens"] += usage.get("total_tokens", 0)
                        state["token_usage"] = curr_usage
                except Exception:
                    state["last_thought"] = "LLM invocation fallback to structured reasoning"

            # Reactive decision logic
            # 1. Not searched yet
            if not candidates and not last_err:
                state["next_tool_name"] = "search_flights"
                state["next_tool_args"] = {
                    "origin": state["origin"],
                    "destination": state["destination"],
                    "date": state.get("date"),
                }
                return state

            # 2. Search yielded 0 valid flights or permanent error
            if candidates is not None and len(candidates) == 0 and last_err != "SOLD_OUT":
                handoff = self.harness.handoff_layer.create_handoff(
                    status=ExecutionStatus.HANDOFF,
                    reason="no_matching_flights",
                    human_question=f"Không tìm thấy chuyến bay phù hợp cho chặng {state['origin']} -> {state['destination']}. Bạn có muốn mở rộng tiêu chí không?",
                    actions_attempted=self.harness.actions_attempted,
                    flights_attempted=self.harness.flights_attempted,
                    traces=self.harness.traces,
                )
                state["status"] = ExecutionStatus.HANDOFF
                state["handoff_package"] = handoff.to_dict()
                state["next_tool_name"] = None
                return state

            # 3. Candidates available, choose/inspect best candidate
            if not selected:
                valid_candidates = []
                for f in candidates:
                    fl_obj = self.airline.flights.get(f["flight_id"])
                    if fl_obj and self.constraints.validate_flight(fl_obj)[0]:
                        valid_candidates.append(f)

                if not valid_candidates:
                    handoff = self.harness.handoff_layer.create_handoff(
                        status=ExecutionStatus.HANDOFF,
                        reason="all_candidates_invalid",
                        human_question="Các chuyến bay tìm thấy đều không thỏa mãn tiêu chí ràng buộc. Bạn muốn thay đổi yêu cầu không?",
                        actions_attempted=self.harness.actions_attempted,
                        flights_attempted=self.harness.flights_attempted,
                        traces=self.harness.traces,
                    )
                    state["status"] = ExecutionStatus.HANDOFF
                    state["handoff_package"] = handoff.to_dict()
                    state["next_tool_name"] = None
                    return state

                chosen = valid_candidates[0]
                state["selected_flight_id"] = chosen["flight_id"]
                if len(valid_candidates) > 1:
                    state["backup_flight_id"] = valid_candidates[1]["flight_id"]

                state["next_tool_name"] = "get_flight_details"
                state["next_tool_args"] = {"flight_id": chosen["flight_id"]}
                return state

            # 4. Check approval before writing
            if not state.get("user_approved", False):
                state["status"] = ExecutionStatus.PENDING_REVIEW
                state["next_tool_name"] = None
                return state

            # 5. Hold booking
            if not hold_id:
                state["next_tool_name"] = "hold_booking"
                state["next_tool_args"] = {
                    "flight_id": state["selected_flight_id"],
                    "passenger_name": state["passenger_name"],
                    "seat_preference": "window",
                }
                return state

            # 6. Confirm booking
            if not booking_id:
                state["next_tool_name"] = "confirm_booking"
                state["next_tool_args"] = {
                    "hold_id": hold_id,
                    "passenger_name": state["passenger_name"],
                }
                return state

            # 7. Verify booking state via tool
            state["next_tool_name"] = "get_booking_details"
            state["next_tool_args"] = {
                "booking_id": booking_id,
                "passenger_name": state["passenger_name"],
            }
            return state

        def react_tool_node(state: AgentState) -> AgentState:
            tool_name = state.get("next_tool_name")
            tool_args = state.get("next_tool_args") or {}

            ok, result, msg = self.harness.execute_tool(
                tool_name=tool_name,
                args=tool_args,
                airline=self.airline,
                tools_dict=self.tools_dict,
                pattern="ReAct",
            )
            state["last_tool_result"] = result

            if ok:
                state["last_error"] = None
                if tool_name == "search_flights":
                    state["candidate_flights"] = result
                elif tool_name == "hold_booking":
                    state["current_hold_id"] = result.get("hold_id")
                elif tool_name == "confirm_booking":
                    state["current_booking_id"] = result.get("booking_id")
                elif tool_name == "get_booking_details":
                    pass
            else:
                err_type = result.get("type", "") if isinstance(result, dict) else ""
                state["last_error"] = err_type or msg

                # Reactive adaptation: If candidate was SOLD_OUT, fallback to backup
                if "SoldOut" in err_type or "SOLD_OUT" in msg:
                    backup = state.get("backup_flight_id")
                    if backup and backup != state.get("selected_flight_id"):
                        state["selected_flight_id"] = backup
                        state["backup_flight_id"] = None
                        state["current_hold_id"] = None
                        state["last_error"] = "SOLD_OUT_RECOVERING"
                    else:
                        handoff = self.harness.handoff_layer.create_handoff(
                            status=ExecutionStatus.HANDOFF,
                            reason="candidate_sold_out_no_backup",
                            human_question="Chuyến bay lựa chọn đã hết chỗ và không còn chuyến dự phòng. Bạn có muốn đổi ngày bay không?",
                            actions_attempted=self.harness.actions_attempted,
                            flights_attempted=self.harness.flights_attempted,
                            traces=self.harness.traces,
                        )
                        state["status"] = ExecutionStatus.HANDOFF
                        state["handoff_package"] = handoff.to_dict()

                elif "PermissionDenied" in err_type:
                    state["status"] = ExecutionStatus.PENDING_REVIEW

                elif "Loop" in msg or "LOOP_DETECTED" in msg:
                    state["status"] = ExecutionStatus.LOOP_DETECTED
                elif "Limit" in msg or "LIMIT_EXCEEDED" in msg:
                    state["status"] = ExecutionStatus.LIMIT_EXCEEDED
                else:
                    handoff = self.harness.handoff_layer.create_handoff(
                        status=ExecutionStatus.HANDOFF,
                        reason=f"tool_failure_{tool_name}",
                        human_question=f"Gặp lỗi khi thực thi {tool_name}: {msg}. Cần sự hỗ trợ của bạn.",
                        actions_attempted=self.harness.actions_attempted,
                        flights_attempted=self.harness.flights_attempted,
                        traces=self.harness.traces,
                    )
                    state["status"] = ExecutionStatus.HANDOFF
            state["next_tool_name"] = None
            state["next_tool_args"] = None
            return state

        def react_eval_termination(state: AgentState) -> AgentState:
            # Code-level verification via CompletionLayer
            booking_id = state.get("current_booking_id")
            if booking_id:
                is_done, details = self.harness.completion_layer.verify_completion(
                    booking_id=booking_id, airline=self.airline
                )
                if is_done:
                    state["status"] = ExecutionStatus.SUCCESS
                    state["completion_details"] = details
                else:
                    state["status"] = ExecutionStatus.ABNORMAL_TERMINATION
                    state["last_error"] = details.get("reason")
            return state

        def react_route(state: AgentState) -> str:
            status = state.get("status")
            if status in [
                ExecutionStatus.SUCCESS,
                ExecutionStatus.PENDING_REVIEW,
                ExecutionStatus.HANDOFF,
                ExecutionStatus.LOOP_DETECTED,
                ExecutionStatus.LIMIT_EXCEEDED,
                ExecutionStatus.ABNORMAL_TERMINATION,
            ]:
                return "end"
            if state.get("next_tool_name"):
                return "call_tool"
            return "reason"

        workflow.add_node("reason", react_reason_node)
        workflow.add_node("tool", react_tool_node)
        workflow.add_node("eval_termination", react_eval_termination)

        workflow.set_entry_point("reason")
        workflow.add_conditional_edges("reason", react_route, {"call_tool": "tool", "end": END, "reason": "reason"})
        workflow.add_edge("tool", "eval_termination")
        workflow.add_conditional_edges("eval_termination", react_route, {"call_tool": "tool", "end": END, "reason": "reason"})

        return workflow.compile()

    # -----------------------------------------------------------------
    # PATTERN 2: Plan-then-Execute Architecture
    # -----------------------------------------------------------------

    def _build_plan_execute_graph(self) -> StateGraph:
        workflow = StateGraph(AgentState)

        def planner_node(state: AgentState) -> AgentState:
            """Generates a structured multi-step plan upfront."""
            state["total_steps"] = state.get("total_steps", 0) + 1
            # Structured plan representation as list of machine-readable steps
            plan = [
                {"step_id": 1, "action": "search", "tool": "search_flights", "args": {"origin": state["origin"], "destination": state["destination"], "date": state.get("date")}},
                {"step_id": 2, "action": "inspect", "tool": "get_flight_details", "args": {"flight_id": "VN101"}},
                {"step_id": 3, "action": "approval_gate", "tool": None, "args": {}},
                {"step_id": 4, "action": "hold", "tool": "hold_booking", "args": {"flight_id": "VN101", "passenger_name": state["passenger_name"], "seat_preference": "window"}},
                {"step_id": 5, "action": "confirm", "tool": "confirm_booking", "args": {"hold_id": "$HOLD_ID", "passenger_name": state["passenger_name"]}},
                {"step_id": 6, "action": "verify", "tool": "get_booking_details", "args": {"booking_id": "$BOOKING_ID", "passenger_name": state["passenger_name"]}},
            ]
            state["plan"] = plan
            state["current_step_index"] = 0
            state["last_thought"] = "Tạo kế hoạch tĩnh 6 bước từ tìm kiếm đến xác nhận."
            return state

        def plan_validator_node(state: AgentState) -> AgentState:
            """Validates upfront that the plan satisfies basic policy."""
            plan = state.get("plan", [])
            if not plan:
                state["status"] = ExecutionStatus.ABNORMAL_TERMINATION
                state["last_error"] = "EmptyPlanError"
            return state

        def executor_node(state: AgentState) -> AgentState:
            """Executes steps sequentially through the harness."""
            plan = state.get("plan", [])
            idx = state.get("current_step_index", 0)

            while idx < len(plan):
                step = plan[idx]
                action = step["action"]

                # Checkpoint: approval gate before write steps
                if action == "approval_gate":
                    if not state.get("user_approved", False):
                        state["status"] = ExecutionStatus.PENDING_REVIEW
                        state["current_step_index"] = idx
                        return state
                    idx += 1
                    continue

                tool_name = step["tool"]
                tool_args = dict(step["args"])

                # Dynamic variable resolution from state
                if tool_args.get("hold_id") == "$HOLD_ID":
                    tool_args["hold_id"] = state.get("current_hold_id")
                if tool_args.get("booking_id") == "$BOOKING_ID":
                    tool_args["booking_id"] = state.get("current_booking_id")

                ok, result, msg = self.harness.execute_tool(
                    tool_name=tool_name,
                    args=tool_args,
                    airline=self.airline,
                    tools_dict=self.tools_dict,
                    pattern="Plan-then-Execute",
                )

                if ok:
                    if tool_name == "search_flights":
                        state["candidate_flights"] = result
                        # If 0 flights found
                        valid = [f for f in result if self.constraints.validate_flight(self.airline.flights.get(f["flight_id"]))[0]] if result else []
                        if not valid:
                            handoff = self.harness.handoff_layer.create_handoff(
                                status=ExecutionStatus.HANDOFF,
                                reason="no_matching_flights",
                                human_question="Không có chuyến bay phù hợp trong kế hoạch ban đầu.",
                                actions_attempted=self.harness.actions_attempted,
                                flights_attempted=self.harness.flights_attempted,
                                traces=self.harness.traces,
                            )
                            state["status"] = ExecutionStatus.HANDOFF
                            state["handoff_package"] = handoff.to_dict()
                            return state

                    elif tool_name == "hold_booking":
                        state["current_hold_id"] = result.get("hold_id")
                    elif tool_name == "confirm_booking":
                        state["current_booking_id"] = result.get("booking_id")

                    idx += 1
                    state["current_step_index"] = idx
                else:
                    # In Plan-then-Execute: a step failure stops execution immediately
                    state["last_error"] = msg
                    handoff = self.harness.handoff_layer.create_handoff(
                        status=ExecutionStatus.HANDOFF,
                        reason=f"plan_step_failed_{step['step_id']}",
                        human_question=f"Bước '{step['action']}' trong kế hoạch thất bại: {msg}. Dừng kế hoạch.",
                        actions_attempted=self.harness.actions_attempted,
                        flights_attempted=self.harness.flights_attempted,
                        traces=self.harness.traces,
                    )
                    state["status"] = ExecutionStatus.HANDOFF
                    state["handoff_package"] = handoff.to_dict()
                    return state

            # Plan finished
            return state

        def verifier_node(state: AgentState) -> AgentState:
            booking_id = state.get("current_booking_id")
            if booking_id:
                is_done, details = self.harness.completion_layer.verify_completion(
                    booking_id=booking_id, airline=self.airline
                )
                if is_done:
                    state["status"] = ExecutionStatus.SUCCESS
                    state["completion_details"] = details
                else:
                    state["status"] = ExecutionStatus.ABNORMAL_TERMINATION
            return state

        workflow.add_node("planner", planner_node)
        workflow.add_node("validator", plan_validator_node)
        workflow.add_node("executor", executor_node)
        workflow.add_node("verifier", verifier_node)

        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "validator")
        workflow.add_edge("validator", "executor")
        workflow.add_edge("executor", "verifier")
        workflow.add_edge("verifier", END)

        return workflow.compile()

    # -----------------------------------------------------------------
    # PATTERN 3: Hybrid Architecture (Planning + Active Replanning)
    # -----------------------------------------------------------------

    def _build_hybrid_graph(self) -> StateGraph:
        workflow = StateGraph(AgentState)

        def hybrid_initial_planner(state: AgentState) -> AgentState:
            state["total_steps"] = state.get("total_steps", 0) + 1
            # Initial phase plan: Discovery phase
            state["plan"] = [
                {"phase": "discovery", "tool": "search_flights", "args": {"origin": state["origin"], "destination": state["destination"], "date": state.get("date")}},
            ]
            state["current_step_index"] = 0
            state["last_thought"] = "Lập kế hoạch giai đoạn 1: Khảo sát và tìm ứng viên."
            return state

        def hybrid_step_executor(state: AgentState) -> AgentState:
            plan = state.get("plan", [])
            idx = state.get("current_step_index", 0)
            if idx >= len(plan):
                return state

            step = plan[idx]
            tool_name = step["tool"]
            tool_args = dict(step["args"])

            # Resolve variables
            if tool_args.get("hold_id") == "$HOLD_ID":
                tool_args["hold_id"] = state.get("current_hold_id")
            if tool_args.get("booking_id") == "$BOOKING_ID":
                tool_args["booking_id"] = state.get("current_booking_id")

            ok, result, msg = self.harness.execute_tool(
                tool_name=tool_name,
                args=tool_args,
                airline=self.airline,
                tools_dict=self.tools_dict,
                pattern="Hybrid",
            )

            state["last_tool_result"] = result
            if ok:
                state["last_error"] = None
                if tool_name == "search_flights":
                    state["candidate_flights"] = result
                elif tool_name == "hold_booking":
                    state["current_hold_id"] = result.get("hold_id")
                elif tool_name == "confirm_booking":
                    state["current_booking_id"] = result.get("booking_id")
                state["current_step_index"] = idx + 1
            else:
                err_type = result.get("type", "") if isinstance(result, dict) else ""
                state["last_error"] = err_type or msg

            return state

        def hybrid_monitor_replanner(state: AgentState) -> AgentState:
            """Inspects environment and dynamically updates or replans subsequent steps."""
            state["total_steps"] = state.get("total_steps", 0) + 1
            last_err = state.get("last_error")
            candidates = state.get("candidate_flights", [])
            selected = state.get("selected_flight_id")

            # 1. If candidate failed due to SOLD_OUT -> Dynamic Replanning!
            if last_err and ("SoldOut" in last_err or "SOLD_OUT" in last_err):
                backup = state.get("backup_flight_id")
                if backup:
                    # Dynamic replan: replace failed flight with backup flight VN102
                    state["selected_flight_id"] = backup
                    state["backup_flight_id"] = None
                    state["last_error"] = None
                    state["plan"] = [
                        {"phase": "inspect_backup", "tool": "get_flight_details", "args": {"flight_id": backup}},
                        {"phase": "hold_backup", "tool": "hold_booking", "args": {"flight_id": backup, "passenger_name": state["passenger_name"], "seat_preference": "window"}},
                        {"phase": "confirm_backup", "tool": "confirm_booking", "args": {"hold_id": "$HOLD_ID", "passenger_name": state["passenger_name"]}},
                    ]
                    state["current_step_index"] = 0
                    state["last_thought"] = f"Phát hiện {selected} hết chỗ! Tái lập kế hoạch tức thời sang chuyến dự phòng {backup}."
                    return state
                else:
                    handoff = self.harness.handoff_layer.create_handoff(
                        status=ExecutionStatus.HANDOFF,
                        reason="sold_out_no_backup",
                        human_question="Chuyến bay hết chỗ và không có chuyến thay thế. Bạn muốn chọn ngày khác?",
                        actions_attempted=self.harness.actions_attempted,
                        flights_attempted=self.harness.flights_attempted,
                        traces=self.harness.traces,
                    )
                    state["status"] = ExecutionStatus.HANDOFF
                    state["handoff_package"] = handoff.to_dict()
                    return state

            # 2. If discovery phase finished, plan booking phase
            if not selected and candidates is not None:
                valid = [f for f in candidates if self.constraints.validate_flight(self.airline.flights.get(f["flight_id"]))[0]]
                if not valid:
                    handoff = self.harness.handoff_layer.create_handoff(
                        status=ExecutionStatus.HANDOFF,
                        reason="no_matching_flights",
                        human_question="Không tìm thấy chuyến bay phù hợp ràng buộc.",
                        actions_attempted=self.harness.actions_attempted,
                        flights_attempted=self.harness.flights_attempted,
                        traces=self.harness.traces,
                    )
                    state["status"] = ExecutionStatus.HANDOFF
                    state["handoff_package"] = handoff.to_dict()
                    return state

                chosen = valid[0]
                state["selected_flight_id"] = chosen["flight_id"]
                if len(valid) > 1:
                    state["backup_flight_id"] = valid[1]["flight_id"]

                # If user approval is not granted -> stop with PENDING_REVIEW before planning write phase
                if not state.get("user_approved", False):
                    state["status"] = ExecutionStatus.PENDING_REVIEW
                    return state

                # Plan Phase 2: Booking execution
                state["plan"] = [
                    {"phase": "inspect", "tool": "get_flight_details", "args": {"flight_id": chosen["flight_id"]}},
                    {"phase": "hold", "tool": "hold_booking", "args": {"flight_id": chosen["flight_id"], "passenger_name": state["passenger_name"], "seat_preference": "window"}},
                    {"phase": "confirm", "tool": "confirm_booking", "args": {"hold_id": "$HOLD_ID", "passenger_name": state["passenger_name"]}},
                ]
                state["current_step_index"] = 0
                state["last_thought"] = f"Lập kế hoạch giai đoạn 2 cho chuyến {chosen['flight_id']}."
                return state

            # 3. Check for permission denied
            if last_err and "PermissionDenied" in last_err:
                state["status"] = ExecutionStatus.PENDING_REVIEW
                return state

            return state

        def hybrid_completion_gate(state: AgentState) -> AgentState:
            booking_id = state.get("current_booking_id")
            if booking_id:
                is_done, details = self.harness.completion_layer.verify_completion(
                    booking_id=booking_id, airline=self.airline
                )
                if is_done:
                    state["status"] = ExecutionStatus.SUCCESS
                    state["completion_details"] = details
                else:
                    state["status"] = ExecutionStatus.ABNORMAL_TERMINATION
            elif not state.get("status"):
                if not state.get("user_approved", False):
                    state["status"] = ExecutionStatus.PENDING_REVIEW
                else:
                    state["status"] = ExecutionStatus.HANDOFF
            return state

        def hybrid_route(state: AgentState) -> str:
            status = state.get("status")
            if status in [
                ExecutionStatus.SUCCESS,
                ExecutionStatus.PENDING_REVIEW,
                ExecutionStatus.HANDOFF,
                ExecutionStatus.LOOP_DETECTED,
                ExecutionStatus.LIMIT_EXCEEDED,
                ExecutionStatus.ABNORMAL_TERMINATION,
            ]:
                return "end"

            plan = state.get("plan", [])
            idx = state.get("current_step_index", 0)
            if idx < len(plan):
                return "exec_step"

            return "end"

        workflow.add_node("planner", hybrid_initial_planner)
        workflow.add_node("exec_step", hybrid_step_executor)
        workflow.add_node("monitor", hybrid_monitor_replanner)
        workflow.add_node("completion", hybrid_completion_gate)

        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "exec_step")
        workflow.add_edge("exec_step", "monitor")
        workflow.add_conditional_edges("monitor", hybrid_route, {"exec_step": "exec_step", "monitor": "monitor", "end": "completion"})
        workflow.add_edge("completion", END)

        return workflow.compile()

    # -----------------------------------------------------------------
    # Unified Run Method
    # -----------------------------------------------------------------

    def run(self, pattern: str = "react", approval: bool = True) -> Dict[str, Any]:
        """Execute the chosen pattern on an isolated execution state."""
        self.user_approved = approval
        self.harness.reset(user_approved=approval)

        initial_state: AgentState = {
            "goal": f"Đặt vé một chiều cho {self.constraints.passenger_name} chặng {self.constraints.origin} -> {self.constraints.destination}",
            "passenger_name": self.constraints.passenger_name,
            "origin": self.constraints.origin,
            "destination": self.constraints.destination,
            "date": None,
            "user_approved": approval,
            "pattern": pattern,
            "candidate_flights": [],
            "selected_flight_id": None,
            "backup_flight_id": None,
            "current_hold_id": None,
            "current_booking_id": None,
            "next_tool_name": None,
            "next_tool_args": None,
            "last_tool_result": None,
            "last_error": None,
            "status": None,
            "handoff_package": None,
            "completion_details": None,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "runtime_sec": 0.0,
            "total_steps": 0,
            "total_tool_calls": 0,
        }

        # Select compiled LangGraph StateGraph
        pat_lower = pattern.lower().replace("-", "_")
        t0 = time.time()
        if pat_lower in ["react"]:
            graph = self._build_react_graph()
        elif pat_lower in ["plan_execute", "plan_then_execute"]:
            graph = self._build_plan_execute_graph()
        elif pat_lower in ["hybrid", "lai"]:
            graph = self._build_hybrid_graph()
        else:
            raise ValueError(f"Không hỗ trợ pattern: {pattern}")

        final_state = graph.invoke(initial_state)
        elapsed = time.time() - t0

        final_state["runtime_sec"] = elapsed
        final_state["total_steps"] = self.harness.step_counter
        final_state["total_tool_calls"] = self.harness.tool_call_counter

        # If booking exists, double check completion
        if final_state.get("current_booking_id"):
            is_ok, comp_details = self.harness.completion_layer.verify_completion(
                final_state["current_booking_id"], self.airline
            )
            if is_ok:
                final_state["status"] = ExecutionStatus.SUCCESS
                final_state["completion_details"] = comp_details

        return final_state
