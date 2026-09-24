"""Tests de l'API admin (lecture seule, dashboard)."""

from fastapi.testclient import TestClient

from app.core.call_session import shared_calendar, shared_call_logs, shared_kb, shared_tickets
from app.llm.tools_rdv import Appointment
from app.main import app, settings
from app.observability.call_logs import CallLogEntry


def _reset_shared_state():
    shared_call_logs._entries.clear()
    shared_calendar.appointments.clear()
    shared_tickets.tickets.clear()


def test_stats_empty_state():
    _reset_shared_state()
    client = TestClient(app)
    resp = client.get("/admin/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "calls_count": 0,
        "avg_latency_ms": None,
        "escalation_rate": None,
        "open_tickets_count": 0,
        "alerts": [],
    }


def test_calls_list_and_detail():
    _reset_shared_state()
    shared_call_logs._entries["CA_test"] = CallLogEntry(
        twilio_call_sid="CA_test",
        use_case="rdv",
        transcript="Appelant : bonjour\nAgent : bonjour !",
        duration_seconds=42,
        outcome="booked",
        escalated_to_human=False,
        avg_turn_latency_ms=850,
        tool_calls_count=2,
    )
    client = TestClient(app)

    listing = client.get("/admin/api/calls").json()
    assert len(listing) == 1
    assert listing[0]["twilio_call_sid"] == "CA_test"
    assert "transcript" not in listing[0]  # pas dans la liste, seulement le détail

    detail = client.get("/admin/api/calls/CA_test").json()
    assert detail["transcript"] == "Appelant : bonjour\nAgent : bonjour !"

    missing = client.get("/admin/api/calls/UNKNOWN")
    assert missing.status_code == 404


def test_appointments_filters_by_window():
    _reset_shared_state()
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(tz=ZoneInfo("Europe/Paris")).date()
    shared_calendar.appointments.append(
        Appointment(1, datetime.combine(today, datetime.min.time()), "Durand", "x")
    )
    shared_calendar.appointments.append(
        Appointment(
            2,
            datetime.combine(today + timedelta(days=30), datetime.min.time()),
            "Loin",
            "x",
        )
    )
    client = TestClient(app)
    result = client.get("/admin/api/appointments?days_ahead=7").json()
    names = [a["nom"] for a in result]
    assert "Durand" in names
    assert "Loin" not in names


def test_tickets_lists_open_only():
    _reset_shared_state()
    shared_tickets.tickets.append(
        {"id": 1, "resume": "x", "priorite": "low", "caller_phone": None, "status": "open"}
    )
    shared_tickets.tickets.append(
        {"id": 2, "resume": "y", "priorite": "low", "caller_phone": None, "status": "closed"}
    )
    client = TestClient(app)
    result = client.get("/admin/api/tickets").json()
    assert [t["id"] for t in result] == [1]


def test_knowledge_base_listing_not_empty():
    client = TestClient(app)
    result = client.get("/admin/api/knowledge-base").json()
    assert len(result) >= 5
    assert all({"id", "question", "answer"} <= set(e) for e in result)


def test_admin_key_required_when_configured():
    settings.admin_api_key = "secret123"
    try:
        client = TestClient(app)
        assert client.get("/admin/api/stats").status_code == 401
        assert client.get("/admin/api/stats", headers={"X-Admin-Key": "wrong"}).status_code == 401
        ok = client.get("/admin/api/stats", headers={"X-Admin-Key": "secret123"})
        assert ok.status_code == 200
    finally:
        settings.admin_api_key = ""


def test_kb_shared_state_isolated_from_call_session_tests():
    # S'assure que shared_kb reste accessible/consistant même après les autres suites
    assert shared_kb is not None
