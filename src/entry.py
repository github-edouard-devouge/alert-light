"""Cloudflare Python Worker entry point.

Receives a Datadog webhook, authenticates it via a shared header,
maps the payload to a LIFX visual effect, and triggers the bulb.

Routes:
  GET  /health   -> {"status": "ok"} (no auth, used for uptime checks)
  POST /webhook  -> requires X-Webhook-Token header matching SHARED_SECRET
"""
from __future__ import annotations

import hmac
import json
import logging
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from lifx_client import LIFXError, apply_effect
from profiles import get_profile

logger = logging.getLogger("alert-light")


def _json(payload: dict, status: int = 200) -> Response:
    """Helper: return a JSON response with explicit content-type."""
    return Response(
        json.dumps(payload),
        status=status,
        headers={"Content-Type": "application/json"},
    )


def _authorized(request, expected_secret: str) -> bool:
    """Constant-time check of the X-Webhook-Token header against the secret."""
    provided = request.headers.get("X-Webhook-Token") or ""
    return hmac.compare_digest(provided, expected_secret)


class Default(WorkerEntrypoint):
    """Worker entry point — Cloudflare invokes `fetch` for every HTTP request."""

    async def fetch(self, request):
        path = urlparse(request.url).path
        method = request.method.upper()

        if method == "GET" and path == "/health":
            return _json({"status": "ok"})

        if method == "POST" and path == "/webhook":
            return await self._handle_webhook(request)

        return _json({"error": "not_found"}, status=404)

    async def _handle_webhook(self, request) -> Response:
        # Fail closed: if SHARED_SECRET is not configured, reject every webhook
        # rather than crashing with 500. A misconfigured server should not
        # accidentally pass auth (the empty-vs-empty compare_digest case) and
        # should not leak its misconfiguration as a stack trace either.
        shared_secret = self._env("SHARED_SECRET")
        if not shared_secret:
            logger.error("SHARED_SECRET is not configured — rejecting webhook")
            return _json({"error": "unauthorized"}, status=401)

        if not _authorized(request, shared_secret):
            return _json({"error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        alert_type = payload.get("alert_type")
        transition = payload.get("transition")
        profile = get_profile(alert_type, transition)

        if profile is None:
            logger.info(
                "ignoring unknown alert_type=%r transition=%r monitor_id=%r",
                alert_type, transition, payload.get("monitor_id"),
            )
            return _json({"status": "ignored", "reason": "unknown_alert_type"}, status=202)

        try:
            await apply_effect(
                profile,
                token=self._require_env("LIFX_TOKEN"),
                selector=self._env("LIFX_SELECTOR", "label:Alert"),
                base_url=self._env("LIFX_BASE_URL", "https://api.lifx.com/v1"),
            )
        except LIFXError as exc:
            logger.error("LIFX call failed: %s", exc)
            return _json({"error": "lifx_failure", "detail": str(exc)}, status=502)

        logger.info(
            "triggered profile=%s monitor_id=%r",
            profile.name, payload.get("monitor_id"),
        )
        return _json({"status": "ok", "profile": profile.name})

    def _env(self, name: str, default: str | None = None) -> str:
        value = getattr(self.env, name, None)
        return value if value is not None else (default or "")

    def _require_env(self, name: str) -> str:
        value = getattr(self.env, name, None)
        if not value:
            raise RuntimeError(f"Missing required binding/secret: {name}")
        return value
