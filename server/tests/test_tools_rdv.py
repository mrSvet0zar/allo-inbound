"""Tests des outils RDV (validation des arguments + logique calendrier)."""

import json
from datetime import date, datetime, time

import pytest

from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor, next_open_day

MONDAY = date(2026, 9, 21)  # un lundi
SATURDAY = date(2026, 9, 26)


@pytest.fixture
def executor():
    return ToolExecutor(InMemoryCalendar(), caller_phone="+33612345678")


async def _call(executor, name, args):
    return json.loads(await executor.execute(name, args))


async def test_check_availability_open_day(executor):
    result = await _call(executor, "check_availability", {"date": MONDAY.isoformat()})
    assert "09:00" in result["creneaux_disponibles"]
    assert "14:30" in result["creneaux_disponibles"]
    assert "12:30" not in result["creneaux_disponibles"]  # pause déjeuner


async def test_check_availability_weekend_empty(executor):
    result = await _call(executor, "check_availability", {"date": SATURDAY.isoformat()})
    assert result["creneaux_disponibles"] == []


async def test_book_then_slot_taken(executor):
    args = {"date": MONDAY.isoformat(), "heure": "10:00", "nom": "Durand", "motif": "consultation"}
    result = await _call(executor, "book_appointment", args)
    assert result["confirme"] is True

    # Le créneau n'est plus disponible
    avail = await _call(executor, "check_availability", {"date": MONDAY.isoformat()})
    assert "10:00" not in avail["creneaux_disponibles"]

    # Double réservation refusée
    result2 = await _call(executor, "book_appointment", {**args, "nom": "Martin"})
    assert "error" in result2


async def test_cancel_flow(executor):
    booked = await _call(
        executor,
        "book_appointment",
        {"date": MONDAY.isoformat(), "heure": "09:00", "nom": "Durand", "motif": "suivi"},
    )
    result = await _call(
        executor, "cancel_appointment", {"appointment_id": booked["appointment_id"]}
    )
    assert result["annule"] is True

    # Créneau de nouveau libre, annulation double refusée
    avail = await _call(executor, "check_availability", {"date": MONDAY.isoformat()})
    assert "09:00" in avail["creneaux_disponibles"]
    again = await _call(
        executor, "cancel_appointment", {"appointment_id": booked["appointment_id"]}
    )
    assert "error" in again


async def test_find_appointment_by_name(executor):
    await _call(
        executor,
        "book_appointment",
        {"date": MONDAY.isoformat(), "heure": "15:00", "nom": "Mme Lefèvre", "motif": "bilan"},
    )
    result = await _call(executor, "find_appointment", {"nom": "lefèvre"})
    assert len(result["rendez_vous"]) == 1
    assert result["rendez_vous"][0]["heure"] == "15:00"


async def test_escalate_sets_flag(executor):
    result = await _call(executor, "escalate_to_human", {"raison": "litige facturation"})
    assert result["transfert_en_cours"] is True
    assert executor.escalation_requested == "litige facturation"


async def test_invalid_date_returns_error_not_crash(executor):
    result = await _call(executor, "check_availability", {"date": "mardi prochain"})
    assert "error" in result


async def test_modify_appointment_flow(executor):
    booked = await _call(
        executor,
        "book_appointment",
        {"date": MONDAY.isoformat(), "heure": "09:00", "nom": "Durand", "motif": "suivi"},
    )
    result = await _call(
        executor,
        "modify_appointment",
        {"appointment_id": booked["appointment_id"], "date": MONDAY.isoformat(), "heure": "16:00"},
    )
    assert result["modifie"] is True
    avail = await _call(executor, "check_availability", {"date": MONDAY.isoformat()})
    assert "09:00" in avail["creneaux_disponibles"]  # ancien créneau libéré
    assert "16:00" not in avail["creneaux_disponibles"]


async def test_modify_unknown_appointment_errors(executor):
    result = await _call(
        executor,
        "modify_appointment",
        {"appointment_id": 999, "date": MONDAY.isoformat(), "heure": "09:00"},
    )
    assert "error" in result


async def test_calendar_booking_stores_phone():
    cal = InMemoryCalendar()
    appt = await cal.book(datetime.combine(MONDAY, time(9, 0)), "Durand", "test", "+336")
    assert appt.caller_phone == "+336"
    assert await cal.find_by_name("durand") == [appt]


def test_next_open_day_skips_weekend():
    assert next_open_day(SATURDAY) == date(2026, 9, 28)  # lundi suivant
    assert next_open_day(MONDAY) == MONDAY
