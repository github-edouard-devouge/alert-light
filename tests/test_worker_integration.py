"""Integration tests against a real local Worker (`pywrangler dev`).

Run with:  pytest -m integration

These are intentionally minimal — the Worker logic is exercised by
test_profiles.py at the unit level. Here we only assert routing, auth
and the JSON contract on the wire.

Note: these tests do NOT call the LIFX API — they assert the auth/routing
boundary. A full end-to-end test against LIFX requires a real token and is
explicitly out of scope.
"""
from __future__ import annotations

import pytest

requests = pytest.importorskip("requests")

pytestmark = pytest.mark.integration


def test_health_returns_ok(dev_server):
    response = requests.get(f"{dev_server}/health", timeout=5)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_is_404(dev_server):
    response = requests.get(f"{dev_server}/nope", timeout=5)
    assert response.status_code == 404


def test_webhook_without_token_is_401(dev_server):
    response = requests.post(
        f"{dev_server}/webhook",
        json={"alert_type": "error", "transition": "Triggered"},
        timeout=5,
    )
    assert response.status_code == 401


def test_webhook_with_wrong_token_is_401(dev_server):
    response = requests.post(
        f"{dev_server}/webhook",
        json={"alert_type": "error", "transition": "Triggered"},
        headers={"X-Webhook-Token": "definitely-not-the-secret"},
        timeout=5,
    )
    assert response.status_code == 401


def test_webhook_empty_body_is_ignored(dev_server, webhook_secret):
    """No alert_type means no profile match. The server should NOT call LIFX
    and should return 202 ignored. Requires the real SHARED_SECRET from
    .dev.vars (otherwise we'd just be testing the 401 branch again)."""
    response = requests.post(
        f"{dev_server}/webhook",
        headers={"X-Webhook-Token": webhook_secret},
        data="",
        timeout=5,
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_webhook_unknown_alert_type_is_ignored(dev_server, webhook_secret):
    """Unknown alert_type with a valid token returns 202 ignored — Datadog
    should keep working even if we introduce new alert types later."""
    response = requests.post(
        f"{dev_server}/webhook",
        headers={"X-Webhook-Token": webhook_secret},
        json={"alert_type": "mystery", "transition": "Triggered"},
        timeout=5,
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
