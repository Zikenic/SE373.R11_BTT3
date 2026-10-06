"""Flight domain models, structured constraints, and status definitions.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Vạn Khải - MSSV: 24520719
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    HANDOFF = "HANDOFF"
    ABNORMAL_TERMINATION = "ABNORMAL_TERMINATION"
    LOOP_DETECTED = "LOOP_DETECTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    ERROR = "ERROR"


class Flight(BaseModel):
    flight_id: str
    airline: str
    origin: str
    destination: str
    departure_date: str  # YYYY-MM-DD
    departure_time: str  # HH:MM
    arrival_time: str    # HH:MM
    price_vnd: int
    available_seats: int
    status: str = "ACTIVE"  # ACTIVE | SOLD_OUT | CANCELLED


class HoldBooking(BaseModel):
    hold_id: str
    flight_id: str
    passenger_name: str
    seat_number: str
    status: str = "ACTIVE"  # ACTIVE | CONFIRMED | RELEASED | EXPIRED
    held_at: str
    expires_at: str


class Booking(BaseModel):
    booking_id: str
    hold_id: str
    flight_id: str
    passenger_name: str
    seat_number: str
    price_vnd: int
    status: str = "confirmed"  # confirmed | cancelled
    created_at: str
    confirmed_at: str


class FlightConstraints(BaseModel):
    """Structured constraints represented as DATA.
    Machine-checkable requirements for flight reservation.
    """
    origin: str = Field(default="SGN", description="Sân bay đi (IATA)")
    destination: str = Field(default="DAD", description="Sân bay đến (IATA)")
    passenger_name: str = Field(default="Bui Van Khai", description="Họ tên hành khách")
    date_min: str = Field(default="2026-10-01", description="Ngày sớm nhất chấp nhận")
    date_max: str = Field(default="2026-10-31", description="Ngày muộn nhất chấp nhận")
    reference_date: str = Field(default="2026-10-06", description="Ngày tham chiếu hiện tại")
    latest_departure_time: str = Field(default="12:00", description="Giờ cất cánh muộn nhất")
    max_price_vnd: int = Field(default=2_000_000, description="Giá vé tối đa chấp nhận (VND)")
    allow_time_boundary_inclusive: bool = Field(
        default=True,
        description="Nếu True: cất cánh <= 12:00 hợp lệ; Nếu False: bắt buộc < 12:00"
    )

    def validate_flight(self, flight: Flight) -> Tuple[bool, str]:
        """Verify whether a flight strictly complies with all structured constraints."""
        if flight.status != "ACTIVE":
            return False, f"Chuyến bay không ở trạng thái ACTIVE (hiện tại: {flight.status})"
        if flight.available_seats <= 0:
            return False, "Chuyến bay đã hết chỗ (available_seats = 0)"
        if flight.origin.upper() != self.origin.upper():
            return False, f"Sai điểm đi: {flight.origin} != {self.origin}"
        if flight.destination.upper() != self.destination.upper():
            return False, f"Sai điểm đến: {flight.destination} != {self.destination}"
        if flight.departure_date < self.reference_date:
            return False, f"Ngày bay {flight.departure_date} đã qua so với ngày hiện tại {self.reference_date}"
        if flight.departure_date < self.date_min or flight.departure_date > self.date_max:
            return False, f"Ngày bay {flight.departure_date} nằm ngoài khoảng yêu cầu [{self.date_min}, {self.date_max}]"
        
        # Time boundary check
        if self.allow_time_boundary_inclusive:
            if flight.departure_time > self.latest_departure_time:
                return False, f"Giờ khởi hành {flight.departure_time} vượt quá giờ giới hạn {self.latest_departure_time}"
        else:
            if flight.departure_time >= self.latest_departure_time:
                return False, f"Giờ khởi hành {flight.departure_time} không trước {self.latest_departure_time}"

        # Price boundary check
        if flight.price_vnd > self.max_price_vnd:
            return False, f"Giá vé {flight.price_vnd:,} VND vượt hạn mức {self.max_price_vnd:,} VND"

        return True, "Chuyến bay thỏa mãn toàn bộ ràng buộc."


@dataclass
class HandoffPackage:
    status: ExecutionStatus
    reason: str
    actions_attempted: List[str] = field(default_factory=list)
    flights_attempted: List[str] = field(default_factory=list)
    booking_id: Optional[str] = None
    hold_id: Optional[str] = None
    trace_summary: List[Dict[str, Any]] = field(default_factory=list)
    human_question: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "actions_attempted": self.actions_attempted,
            "flights_attempted": self.flights_attempted,
            "booking_id": self.booking_id,
            "hold_id": self.hold_id,
            "trace_summary": self.trace_summary,
            "human_question": self.human_question,
        }


@dataclass
class RunLimits:
    max_steps: int = 10
    max_tool_calls: int = 15
    max_runtime_sec: float = 60.0
    max_retries: int = 2
    max_repeated_actions: int = 2


@dataclass
class TraceRecord:
    step_index: int
    pattern: str
    action: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    harness_verdict: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "pattern": self.pattern,
            "action": self.action,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "harness_verdict": self.harness_verdict,
            "message": self.message,
            "timestamp": self.timestamp,
        }
