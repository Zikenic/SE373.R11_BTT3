"""Automated Unit Tests for Flight Reservation Agent and Safety Harness.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Văn Khải - MSSV: 24520719
"""

import sys
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from flight_domain import (
    ExecutionStatus,
    Flight,
    FlightConstraints,
    RunLimits,
)
from harness import (
    CompletionLayer,
    ConstraintLayer,
    FlightHarness,
    PermissionLayer,
)
from mock_airline import (
    AirlineServiceUnavailableError,
    MockAirline,
    OwnershipViolationError,
)
from mock_tools import create_airline_tools
from agents import FlightAgent


class TestFlightHarnessLayers(unittest.TestCase):
    """Test individual harness layers as separate, verifiable units."""

    def setUp(self):
        self.airline = MockAirline()
        self.constraints = FlightConstraints(
            origin="SGN",
            destination="DAD",
            passenger_name="Bui Van Khai",
            date_min="2026-10-01",
            date_max="2026-10-31",
            reference_date="2026-10-06",
            latest_departure_time="12:00",
            max_price_vnd=2_000_000,
        )
        self.constraint_layer = ConstraintLayer(self.constraints)
        self.permission_layer = PermissionLayer(
            user_approved=False, authorized_passenger="Bui Van Khai"
        )
        self.completion_layer = CompletionLayer(self.constraints)

    # -------------------------------------------------------------
    # 1. Constraint Layer Tests
    # -------------------------------------------------------------

    def test_constraint_valid_flight(self):
        """A normal valid flight must pass all constraint checks."""
        flight = self.airline.flights["VN101"]
        is_ok, msg = self.constraint_layer.validate_flight(flight)
        self.assertTrue(is_ok, f"Expected PASS for VN101: {msg}")

    def test_constraint_exact_time_boundary(self):
        """Flight VN103 departs exactly at 12:00 (latest allowed departure time)."""
        flight = self.airline.flights["VN103"]
        self.assertEqual(flight.departure_time, "12:00")
        is_ok, msg = self.constraint_layer.validate_flight(flight)
        self.assertTrue(is_ok, f"Exact time boundary 12:00 should pass: {msg}")

        # When strict < 12:00 is enforced:
        strict_constraints = FlightConstraints(
            origin="SGN",
            destination="DAD",
            allow_time_boundary_inclusive=False,
            latest_departure_time="12:00",
        )
        strict_layer = ConstraintLayer(strict_constraints)
        is_ok_strict, msg_strict = strict_layer.validate_flight(flight)
        self.assertFalse(is_ok_strict, "Strict time boundary must reject exactly 12:00")

    def test_constraint_price_boundary(self):
        """Flight VN104 costs 2,050,000 VND (> 2,000,000 VND max) -> must be rejected."""
        flight = self.airline.flights["VN104"]
        is_ok, msg = self.constraint_layer.validate_flight(flight)
        self.assertFalse(is_ok, "Price 2,050,000 VND must be rejected")
        self.assertIn("vượt hạn mức", msg)

    def test_constraint_invalid_route(self):
        """Flight VN201 goes to HAN instead of DAD -> must be rejected."""
        flight = self.airline.flights["VN201"]
        is_ok, msg = self.constraint_layer.validate_flight(flight)
        self.assertFalse(is_ok, "Wrong destination must be rejected")
        self.assertIn("Sai điểm đến", msg)

    def test_constraint_date_in_past(self):
        """Flight VN099 departure date is 2026-10-04, before reference date 2026-10-06."""
        flight = self.airline.flights["VN099"]
        is_ok, msg = self.constraint_layer.validate_flight(flight)
        self.assertFalse(is_ok, "Past date must be rejected")
        self.assertIn("đã qua", msg)

    # -------------------------------------------------------------
    # 2. Permission Layer Tests
    # -------------------------------------------------------------

    def test_permission_read_tools_allowed(self):
        """Read-only operations are permitted without prior user approval."""
        ok, msg = self.permission_layer.check_permission(
            tool_name="search_flights",
            args={"origin": "SGN", "destination": "DAD"},
            airline=self.airline,
        )
        self.assertTrue(ok, "search_flights should be allowed without approval")

    def test_permission_write_tools_denied_without_approval(self):
        """Write operations (hold, confirm, cancel) must be blocked without approval."""
        self.permission_layer.set_approval(False)
        ok, msg = self.permission_layer.check_permission(
            tool_name="hold_booking",
            args={"flight_id": "VN101", "passenger_name": "Bui Van Khai"},
            airline=self.airline,
        )
        self.assertFalse(ok, "hold_booking must be denied when approval=False")
        self.assertIn("bị từ chối", msg)

    def test_permission_passenger_ownership(self):
        """Agent must not inspect or operate on another passenger's booking."""
        self.permission_layer.set_approval(True)
        # Attempt to operate under a different passenger name
        ok, msg = self.permission_layer.check_permission(
            tool_name="hold_booking",
            args={"flight_id": "VN101", "passenger_name": "Tran Thi B"},
            airline=self.airline,
        )
        self.assertFalse(ok, "Operating on another passenger must be rejected")
        self.assertIn("Vi phạm quyền sở hữu", msg)

    # -------------------------------------------------------------
    # 3. Completion Layer Tests
    # -------------------------------------------------------------

    def test_completion_valid_confirmed_booking(self):
        """Completion check must pass when booking is confirmed and complies with policy."""
        hold = self.airline.hold_booking("VN101", "Bui Van Khai")
        bkg = self.airline.confirm_booking(hold["hold_id"], "Bui Van Khai")

        is_done, details = self.completion_layer.verify_completion(
            booking_id=bkg["booking_id"], airline=self.airline
        )
        self.assertTrue(is_done, f"Expected completion check to PASS: {details}")
        self.assertEqual(details["status"], "confirmed")

    def test_completion_unconfirmed_hold_fails(self):
        """Hold exists but is not yet confirmed -> completion must fail."""
        hold = self.airline.hold_booking("VN101", "Bui Van Khai")
        is_done, details = self.completion_layer.verify_completion(
            booking_id=hold["hold_id"], airline=self.airline
        )
        self.assertFalse(is_done, "Unconfirmed hold must not pass completion")

    def test_completion_wrong_passenger_fails(self):
        """A confirmed booking belonging to another passenger must fail completion."""
        # Create hold & booking for another person directly in airline
        self.airline.flights["VN101"].available_seats = 5
        hold = self.airline.hold_booking("VN101", "Nguyen Van A")
        bkg = self.airline.confirm_booking(hold["hold_id"], "Nguyen Van A")

        is_done, details = self.completion_layer.verify_completion(
            booking_id=bkg["booking_id"], airline=self.airline
        )
        self.assertFalse(is_done, "Booking for another person must fail completion")
        self.assertIn("không đúng với yêu cầu", details["reason"])


class TestSafetyHarnessAndLoopDetection(unittest.TestCase):
    """Test termination conditions, loop detection, and transient retries."""

    def setUp(self):
        self.airline = MockAirline()
        self.constraints = FlightConstraints(passenger_name="Bui Van Khai")
        self.tools = create_airline_tools(self.airline)
        self.tools_dict = {t.name: t for t in self.tools}

    def test_repeated_action_loop_detection(self):
        """Repeated identical tool calls must trigger loop detection."""
        limits = RunLimits(max_repeated_actions=2)
        harness = FlightHarness(
            constraints=self.constraints, user_approved=True, limits=limits
        )

        args = {"origin": "SGN", "destination": "DAD", "date": None}
        ok1, res1, _ = harness.execute_tool("search_flights", args, self.airline, self.tools_dict)
        self.assertTrue(ok1)

        ok2, res2, _ = harness.execute_tool("search_flights", args, self.airline, self.tools_dict)
        self.assertTrue(ok2)

        # 3rd identical call triggers loop detector
        ok3, res3, msg3 = harness.execute_tool("search_flights", args, self.airline, self.tools_dict)
        self.assertFalse(ok3)
        self.assertIn("Phát hiện lặp vô hạn", msg3)
        self.assertEqual(res3.get("status"), ExecutionStatus.LOOP_DETECTED)

    def test_max_step_limit_enforced(self):
        """Exceeding max steps must terminate execution abnormally."""
        limits = RunLimits(max_steps=2)
        harness = FlightHarness(
            constraints=self.constraints, user_approved=True, limits=limits
        )

        harness.execute_tool("get_flight_details", {"flight_id": "VN101"}, self.airline, self.tools_dict)
        harness.execute_tool("get_flight_details", {"flight_id": "VN102"}, self.airline, self.tools_dict)

        # 3rd step exceeds limit of 2
        ok3, res3, msg3 = harness.execute_tool(
            "get_flight_details", {"flight_id": "VN103"}, self.airline, self.tools_dict
        )
        self.assertFalse(ok3)
        self.assertEqual(res3.get("status"), ExecutionStatus.LIMIT_EXCEEDED)

    def test_transient_tool_retry_recovery(self):
        """Harness must retry and succeed on transient service error."""
        self.airline.simulate_transient_failure("search_flights", count=1)
        harness = FlightHarness(constraints=self.constraints, user_approved=True)

        ok, res, msg = harness.execute_tool(
            "search_flights",
            {"origin": "SGN", "destination": "DAD", "date": None},
            self.airline,
            self.tools_dict,
        )
        self.assertTrue(ok, "Harness should transparently retry and succeed")
        self.assertGreater(harness.tool_call_counter, 1, "Tool call counter must record retry")


class TestAgentArchitectures(unittest.TestCase):
    """Test full agent runs across all three patterns."""

    def test_react_normal_booking(self):
        airline = MockAirline()
        constraints = FlightConstraints(passenger_name="Bui Van Khai")
        agent = FlightAgent(airline=airline, constraints=constraints, user_approved=True)
        res = agent.run(pattern="react", approval=True)

        self.assertEqual(res["status"], ExecutionStatus.SUCCESS)
        self.assertIsNotNone(res["completion_details"])
        self.assertEqual(res["completion_details"]["flight_id"], "VN101")

    def test_plan_execute_normal_booking(self):
        airline = MockAirline()
        constraints = FlightConstraints(passenger_name="Bui Van Khai")
        agent = FlightAgent(airline=airline, constraints=constraints, user_approved=True)
        res = agent.run(pattern="plan_execute", approval=True)

        self.assertEqual(res["status"], ExecutionStatus.SUCCESS)
        self.assertIsNotNone(res["completion_details"])
        self.assertEqual(res["completion_details"]["flight_id"], "VN101")

    def test_hybrid_sold_out_adaptation(self):
        """Hybrid must adapt to sold-out preferred flight by replanning to backup."""
        airline = MockAirline()
        airline.simulate_sold_out("VN101")
        constraints = FlightConstraints(passenger_name="Bui Van Khai")
        agent = FlightAgent(airline=airline, constraints=constraints, user_approved=True)
        res = agent.run(pattern="hybrid", approval=True)

        self.assertEqual(res["status"], ExecutionStatus.SUCCESS)
        self.assertIsNotNone(res["completion_details"])
        self.assertEqual(res["completion_details"]["flight_id"], "VN102")


if __name__ == "__main__":
    unittest.main(verbosity=2)
