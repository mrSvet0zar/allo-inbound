"""Alerting basique (cf CLAUDE.md) : dérive du taux d'escalade et de la latence.

Pas de canal d'envoi réel dans ce portfolio (Slack/email) — `check_alerts`
calcule les signaux à partir des derniers appels ; le dashboard admin les
affiche, et un job planifié pourrait les pousser vers un webhook plus tard.
"""

from dataclasses import dataclass

from app.observability.call_logs import CallLogEntry

# Objectifs du CLAUDE.md
TARGET_AVG_LATENCY_MS = 1200
TARGET_P95_LATENCY_MS = 2000

# Seuils d'alerte (au-delà, signal que l'agent galère ou dérive)
ESCALATION_RATE_THRESHOLD = 0.30  # 30% des appels escaladés = anormal
MIN_CALLS_FOR_ESCALATION_ALERT = 5  # évite les faux positifs sur peu d'appels


@dataclass
class Alert:
    level: str  # "warning" | "critical"
    message: str


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct), len(ordered) - 1)
    return float(ordered[idx])


def check_alerts(recent_calls: list[CallLogEntry]) -> list[Alert]:
    """Analyse les derniers appels et retourne les alertes actives."""
    alerts: list[Alert] = []
    if not recent_calls:
        return alerts

    if len(recent_calls) >= MIN_CALLS_FOR_ESCALATION_ALERT:
        escalation_rate = sum(1 for c in recent_calls if c.escalated_to_human) / len(recent_calls)
        if escalation_rate > ESCALATION_RATE_THRESHOLD:
            alerts.append(
                Alert(
                    "warning",
                    f"Taux d'escalade élevé : {escalation_rate:.0%} des "
                    f"{len(recent_calls)} derniers appels (seuil {ESCALATION_RATE_THRESHOLD:.0%}).",
                )
            )

    latencies = [c.avg_turn_latency_ms for c in recent_calls if c.avg_turn_latency_ms is not None]
    if latencies:
        avg = sum(latencies) / len(latencies)
        p95 = _percentile(latencies, 0.95)
        if avg > TARGET_AVG_LATENCY_MS:
            alerts.append(
                Alert(
                    "warning",
                    f"Latence moyenne dégradée : {avg:.0f}ms (objectif < {TARGET_AVG_LATENCY_MS}ms).",
                )
            )
        if p95 > TARGET_P95_LATENCY_MS:
            alerts.append(
                Alert(
                    "critical",
                    f"Latence P95 dégradée : {p95:.0f}ms (objectif < {TARGET_P95_LATENCY_MS}ms).",
                )
            )

    return alerts
