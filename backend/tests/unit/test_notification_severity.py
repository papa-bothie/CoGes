"""Gravité d'une alerte : dérivée de son type, par le serveur seul (ADR 0059)."""

from __future__ import annotations

import pytest

from app.modules.notifications.schemas import NotificationType, severity_of


@pytest.mark.parametrize(
    ("notification_type", "expected"),
    [
        (NotificationType.STOCK_OUT, "critical"),
        (NotificationType.INSIGHT_CRITICAL, "critical"),
        (NotificationType.STOCK_LOW, "warning"),
        (NotificationType.DEBT_DUE, "warning"),
        (NotificationType.SALE_CANCELLED, "warning"),
        (NotificationType.FORECAST_ALERT, "warning"),
    ],
)
def test_every_alert_type_has_a_severity(notification_type: str, expected: str) -> None:
    assert severity_of(notification_type) == expected


def test_no_alert_type_is_left_neutral() -> None:
    assert {severity_of(kind) for kind in NotificationType} == {"warning", "critical"}
