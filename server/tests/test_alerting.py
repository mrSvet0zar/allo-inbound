"""Tests de l'alerting basique (dérive du taux d'escalade / de la latence)."""

from app.observability.alerting import (
    ESCALATION_RATE_THRESHOLD,
    TARGET_AVG_LATENCY_MS,
    check_alerts,
)
from app.observability.call_logs import CallLogEntry


def _call(outcome="resolved", escalated=False, avg_latency_ms=800):
    return CallLogEntry(
        twilio_call_sid=f"CA{id(object())}",
        use_case="support",
        transcript="",
        duration_seconds=60,
        outcome=outcome,
        escalated_to_human=escalated,
        avg_turn_latency_ms=avg_latency_ms,
        tool_calls_count=1,
    )


def test_no_alerts_when_healthy():
    calls = [_call() for _ in range(10)]
    assert check_alerts(calls) == []


def test_no_alerts_on_empty_history():
    assert check_alerts([]) == []


def test_escalation_rate_alert_above_threshold():
    calls = [_call(escalated=True) for _ in range(4)] + [_call() for _ in range(6)]
    alerts = check_alerts(calls)
    assert any("escalade" in a.message for a in alerts)


def test_escalation_rate_no_alert_below_min_calls():
    # 100% d'escalade mais trop peu d'appels pour être significatif
    calls = [_call(escalated=True) for _ in range(3)]
    alerts = check_alerts(calls)
    assert not any("escalade" in a.message for a in alerts)


def test_escalation_rate_no_alert_at_threshold_boundary():
    n_escalated = int(ESCALATION_RATE_THRESHOLD * 10)
    calls = [_call(escalated=True) for _ in range(n_escalated)] + [
        _call() for _ in range(10 - n_escalated)
    ]
    alerts = check_alerts(calls)
    assert not any("escalade" in a.message for a in alerts)


def test_avg_latency_alert():
    calls = [_call(avg_latency_ms=TARGET_AVG_LATENCY_MS + 500) for _ in range(5)]
    alerts = check_alerts(calls)
    assert any(a.level == "warning" and "moyenne" in a.message for a in alerts)


def test_p95_latency_alert_is_critical():
    calls = [_call(avg_latency_ms=900) for _ in range(19)] + [_call(avg_latency_ms=5000)]
    alerts = check_alerts(calls)
    assert any(a.level == "critical" and "P95" in a.message for a in alerts)


def test_calls_without_latency_are_ignored():
    calls = [_call(avg_latency_ms=None) for _ in range(10)]
    assert check_alerts(calls) == []
