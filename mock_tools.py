"""LangChain tools for the mock airline domain.
Provides tools with explicit names, descriptions, and Pydantic schemas.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Vạn Khải - MSSV: 24520719
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool, StructuredTool
from mock_airline import MockAirline


# --- Pydantic Schemas for Tool Arguments ---

class SearchFlightsInput(BaseModel):
    origin: str = Field(description="Mã sân bay khởi hành (IATA, ví dụ: 'SGN')")
    destination: str = Field(description="Mã sân bay đến (IATA, ví dụ: 'DAD')")
    date: Optional[str] = Field(default=None, description="Ngày khởi hành dạng YYYY-MM-DD (tùy chọn)")


class GetFlightDetailsInput(BaseModel):
    flight_id: str = Field(description="Mã chuyến bay (ví dụ: 'VN101')")


class HoldBookingInput(BaseModel):
    flight_id: str = Field(description="Mã chuyến bay cần giữ chỗ (ví dụ: 'VN101')")
    passenger_name: str = Field(description="Họ tên đầy đủ của hành khách (ví dụ: 'Bui Van Khai')")
    seat_preference: str = Field(default="window", description="Sở thích chỗ ngồi ('window' hoặc 'aisle')")


class ConfirmBookingInput(BaseModel):
    hold_id: str = Field(description="Mã giữ chỗ trước đó (ví dụ: 'HLD-0001')")
    passenger_name: str = Field(description="Họ tên đầy đủ của hành khách")


class GetBookingDetailsInput(BaseModel):
    booking_id: str = Field(description="Mã vé đặt (ví dụ: 'BKG-0001')")
    passenger_name: str = Field(description="Họ tên hành khách sở hữu vé để kiểm tra quyền")


class CancelHoldInput(BaseModel):
    hold_id: str = Field(description="Mã giữ chỗ cần hủy (ví dụ: 'HLD-0001')")
    passenger_name: str = Field(description="Họ tên hành khách sở hữu giữ chỗ")


def create_airline_tools(airline: MockAirline) -> List[StructuredTool]:
    """Factory creating LangChain tools wired to an isolated MockAirline instance."""

    @tool(args_schema=SearchFlightsInput)
    def search_flights(origin: str, destination: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tìm kiếm các chuyến bay theo mã sân bay đi, đến và ngày bay tùy chọn."""
        return airline.search_flights(origin=origin, destination=destination, date=date)

    @tool(args_schema=GetFlightDetailsInput)
    def get_flight_details(flight_id: str) -> Dict[str, Any]:
        """Xem thông tin chi tiết của chuyến bay bao gồm giá vé, số ghế trống, giờ bay."""
        return airline.get_flight_details(flight_id=flight_id)

    @tool(args_schema=HoldBookingInput)
    def hold_booking(flight_id: str, passenger_name: str, seat_preference: str = "window") -> Dict[str, Any]:
        """Tạm giữ chỗ một vé trên chuyến bay. Thao tác ghi yêu cầu quyền phê duyệt."""
        return airline.hold_booking(
            flight_id=flight_id, passenger_name=passenger_name, seat_preference=seat_preference
        )

    @tool(args_schema=ConfirmBookingInput)
    def confirm_booking(hold_id: str, passenger_name: str) -> Dict[str, Any]:
        """Xác nhận đặt vé chính thức từ mã giữ chỗ. Thao tác ghi yêu cầu quyền phê duyệt."""
        return airline.confirm_booking(hold_id=hold_id, passenger_name=passenger_name)

    @tool(args_schema=GetBookingDetailsInput)
    def get_booking_details(booking_id: str, passenger_name: str) -> Dict[str, Any]:
        """Tra cứu thông tin vé đã đặt theo mã vé và tên hành khách (bảo vệ quyền sở hữu)."""
        return airline.get_booking_details(booking_id=booking_id, passenger_name=passenger_name)

    @tool(args_schema=CancelHoldInput)
    def cancel_hold(hold_id: str, passenger_name: str) -> Dict[str, Any]:
        """Hủy bỏ lệnh giữ chỗ tạm thời và giải phóng ghế."""
        return airline.cancel_hold(hold_id=hold_id, passenger_name=passenger_name)

    return [
        search_flights,
        get_flight_details,
        hold_booking,
        confirm_booking,
        get_booking_details,
        cancel_hold,
    ]
