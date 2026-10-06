"""Mock Airline domain and local in-memory booking store.
Provides deterministic data for testing and benchmarking.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Vạn Khải - MSSV: 24520719
"""

from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional
from flight_domain import Flight, HoldBooking, Booking


class MockAirlineError(Exception):
    """Base exception for mock airline domain."""
    pass


class FlightNotFoundError(MockAirlineError):
    pass


class FlightSoldOutError(MockAirlineError):
    pass


class HoldNotFoundError(MockAirlineError):
    pass


class BookingNotFoundError(MockAirlineError):
    pass


class OwnershipViolationError(MockAirlineError):
    pass


class AirlineServiceUnavailableError(MockAirlineError):
    """Represents a temporary service failure for retry testing."""
    pass


class MockAirline:
    """Completely local, deterministic airline database and transaction manager."""

    def __init__(self):
        self.flights: Dict[str, Flight] = {}
        self.holds: Dict[str, HoldBooking] = {}
        self.bookings: Dict[str, Booking] = {}
        self._hold_counter = 1
        self._booking_counter = 1
        self._transient_errors: Dict[str, int] = {}
        self.init_default_data()

    def init_default_data(self) -> None:
        """Seed deterministic dataset with realistic boundary test cases."""
        default_flights = [
            # 1. Valid primary flight: SGN -> DAD, within price, before 12:00
            Flight(
                flight_id="VN101",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-10",
                departure_time="09:15",
                arrival_time="10:35",
                price_vnd=1_650_000,
                available_seats=5,
                status="ACTIVE",
            ),
            # 2. Valid backup flight: SGN -> DAD, within price, before 12:00
            Flight(
                flight_id="VN102",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-12",
                departure_time="10:45",
                arrival_time="12:05",
                price_vnd=1_850_000,
                available_seats=4,
                status="ACTIVE",
            ),
            # 3. Exact boundary departure time: exactly 12:00
            Flight(
                flight_id="VN103",
                airline="Vietjet Air",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-10",
                departure_time="12:00",
                arrival_time="13:20",
                price_vnd=1_400_000,
                available_seats=3,
                status="ACTIVE",
            ),
            # 4. Exact boundary price: 2,050,000 VND (above 2,000,000 VND max limit)
            Flight(
                flight_id="VN104",
                airline="Bamboo Airways",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-11",
                departure_time="08:30",
                arrival_time="09:50",
                price_vnd=2_050_000,
                available_seats=2,
                status="ACTIVE",
            ),
            # 5. Sold-out flight: 0 seats available
            Flight(
                flight_id="VN105",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-10",
                departure_time="07:00",
                arrival_time="08:20",
                price_vnd=1_500_000,
                available_seats=0,
                status="SOLD_OUT",
            ),
            # 6. Wrong destination: SGN -> HAN
            Flight(
                flight_id="VN201",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="HAN",
                departure_date="2026-10-10",
                departure_time="09:00",
                arrival_time="11:10",
                price_vnd=1_750_000,
                available_seats=6,
                status="ACTIVE",
            ),
            # 7. Date outside target month: 2026-11-05
            Flight(
                flight_id="VN301",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="DAD",
                departure_date="2026-11-05",
                departure_time="09:00",
                arrival_time="10:20",
                price_vnd=1_600_000,
                available_seats=8,
                status="ACTIVE",
            ),
            # 8. Date in the past relative to reference date (2026-10-06)
            Flight(
                flight_id="VN099",
                airline="Vietnam Airlines",
                origin="SGN",
                destination="DAD",
                departure_date="2026-10-04",
                departure_time="08:00",
                arrival_time="09:20",
                price_vnd=1_600_000,
                available_seats=4,
                status="ACTIVE",
            ),
        ]
        self.flights = {f.flight_id: f for f in default_flights}
        self.holds.clear()
        self.bookings.clear()
        self._hold_counter = 1
        self._booking_counter = 1
        self._transient_errors.clear()

    def simulate_sold_out(self, flight_id: str) -> None:
        """Mark a flight as sold out during runtime."""
        if flight_id in self.flights:
            self.flights[flight_id].available_seats = 0
            self.flights[flight_id].status = "SOLD_OUT"

    def simulate_transient_failure(self, tool_name: str, count: int = 1) -> None:
        """Configure a tool to fail N times with a transient error."""
        self._transient_errors[tool_name] = count

    def _check_transient_failure(self, tool_name: str) -> None:
        """Helper to trigger and decrement transient errors."""
        remaining = self._transient_errors.get(tool_name, 0)
        if remaining > 0:
            self._transient_errors[tool_name] = remaining - 1
            raise AirlineServiceUnavailableError(
                f"Dịch vụ {tool_name} tạm thời quá tải hoặc không phản hồi (thử lại sau)."
            )

    # -------------------------------------------------------------
    # Domain Operations
    # -------------------------------------------------------------

    def search_flights(
        self, origin: str, destination: str, date: Optional[str] = None
    ) -> List[Dict]:
        """Search available flights by route and optional date."""
        self._check_transient_failure("search_flights")
        res = []
        for f in self.flights.values():
            if f.origin.upper() == origin.upper() and f.destination.upper() == destination.upper():
                if date is None or f.departure_date == date:
                    res.append(f.model_dump())
        return res

    def get_flight_details(self, flight_id: str) -> Dict:
        """Retrieve latest flight information and remaining seats."""
        self._check_transient_failure("get_flight_details")
        f = self.flights.get(flight_id)
        if not f:
            raise FlightNotFoundError(f"Không tìm thấy chuyến bay mã {flight_id}")
        return f.model_dump()

    def hold_booking(
        self, flight_id: str, passenger_name: str, seat_preference: str = "window"
    ) -> Dict:
        """Place a temporary seat hold on a flight."""
        self._check_transient_failure("hold_booking")
        flight = self.flights.get(flight_id)
        if not flight:
            raise FlightNotFoundError(f"Không tìm thấy chuyến bay {flight_id}")
        if flight.status != "ACTIVE" or flight.available_seats <= 0:
            raise FlightSoldOutError(f"Chuyến bay {flight_id} đã hết chỗ hoặc không hoạt động")

        flight.available_seats -= 1
        if flight.available_seats == 0:
            flight.status = "SOLD_OUT"

        hold_id = f"HLD-{self._hold_counter:04d}"
        self._hold_counter += 1
        seat_num = f"{12 + self._hold_counter}A" if seat_preference == "window" else f"{12 + self._hold_counter}C"

        now_str = datetime.now().isoformat()
        hold = HoldBooking(
            hold_id=hold_id,
            flight_id=flight_id,
            passenger_name=passenger_name,
            seat_number=seat_num,
            status="ACTIVE",
            held_at=now_str,
            expires_at=now_str,
        )
        self.holds[hold_id] = hold
        return hold.model_dump()

    def confirm_booking(self, hold_id: str, passenger_name: str) -> Dict:
        """Confirm a temporary hold and issue an official booking."""
        self._check_transient_failure("confirm_booking")
        hold = self.holds.get(hold_id)
        if not hold:
            raise HoldNotFoundError(f"Không tìm thấy lệnh giữ chỗ {hold_id}")
        if hold.status != "ACTIVE":
            raise MockAirlineError(f"Lệnh giữ chỗ {hold_id} không ở trạng thái ACTIVE (hiện tại: {hold.status})")
        
        # Ownership check
        if hold.passenger_name.strip().lower() != passenger_name.strip().lower():
            raise OwnershipViolationError(
                f"Vi phạm quyền sở hữu: Hành khách '{passenger_name}' không phải chủ giữ chỗ '{hold.passenger_name}'"
            )

        flight = self.flights.get(hold.flight_id)
        if not flight:
            raise FlightNotFoundError(f"Chuyến bay {hold.flight_id} không tồn tại")

        booking_id = f"BKG-{self._booking_counter:04d}"
        self._booking_counter += 1
        now_str = datetime.now().isoformat()

        booking = Booking(
            booking_id=booking_id,
            hold_id=hold_id,
            flight_id=hold.flight_id,
            passenger_name=passenger_name,
            seat_number=hold.seat_number,
            price_vnd=flight.price_vnd,
            status="confirmed",
            created_at=now_str,
            confirmed_at=now_str,
        )
        hold.status = "CONFIRMED"
        self.bookings[booking_id] = booking
        return booking.model_dump()

    def get_booking_details(self, booking_id: str, passenger_name: str) -> Dict:
        """Inspect booking details with strict passenger ownership verification."""
        self._check_transient_failure("get_booking_details")
        b = self.bookings.get(booking_id)
        if not b:
            raise BookingNotFoundError(f"Không tìm thấy mã đặt vé {booking_id}")
        if b.passenger_name.strip().lower() != passenger_name.strip().lower():
            raise OwnershipViolationError(
                f"Vi phạm quyền sở hữu: Không thể xem vé của hành khách khác ({b.passenger_name} != {passenger_name})"
            )
        return b.model_dump()

    def cancel_hold(self, hold_id: str, passenger_name: str) -> Dict:
        """Release a temporary seat hold."""
        self._check_transient_failure("cancel_hold")
        hold = self.holds.get(hold_id)
        if not hold:
            raise HoldNotFoundError(f"Không tìm thấy lệnh giữ chỗ {hold_id}")
        if hold.passenger_name.strip().lower() != passenger_name.strip().lower():
            raise OwnershipViolationError(
                f"Vi phạm quyền sở hữu: Không thể hủy giữ chỗ của người khác ({hold.passenger_name})"
            )
        if hold.status != "ACTIVE":
            raise MockAirlineError(f"Giữ chỗ {hold_id} đã kết thúc trạng thái ACTIVE ({hold.status})")

        hold.status = "RELEASED"
        flight = self.flights.get(hold.flight_id)
        if flight:
            flight.available_seats += 1
            if flight.status == "SOLD_OUT":
                flight.status = "ACTIVE"
        return {"status": "RELEASED", "hold_id": hold_id, "message": "Đã hủy giữ chỗ thành công"}
