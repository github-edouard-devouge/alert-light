"""Minimal client for the LIFX HTTP Cloud API, using the Worker `fetch` global.

We deliberately avoid `requests` because it is not available inside the
Cloudflare Python Worker runtime (Pyodide). The `workers.fetch` wrapper is
async and returns a Response with `.status` and `.text()` / `.json()`.
"""
from __future__ import annotations

import json
from typing import Any

from profiles import Profile


class LIFXError(RuntimeError):
    """Raised when LIFX cannot deliver the effect: HTTP error, network failure,
    or every targeted bulb returning a non-`ok` status (e.g. offline)."""


def _check_lifx_results(payload: Any) -> None:
    """Raise LIFXError if LIFX accepted the HTTP call but no bulb was reached.

    LIFX returns `HTTP 207 Multi-Status` with a `results[]` array, one entry
    per bulb in the selector. Each entry has a `status` field — `ok`,
    `offline`, `timed_out`, ... A 207 where every bulb is non-`ok` looks
    like success at the HTTP layer but means nothing happened physically.
    We surface that as a hard error so callers (and Datadog) see a 502
    instead of a silent black hole.

    Partial success (at least one bulb `ok`) is treated as success: the
    alert was delivered to *some* lamp, which is what we care about. The
    caller can log the partial-failure detail if desired.
    """
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        # No results array — either an unusual payload or an endpoint that
        # doesn't return per-bulb status. Nothing to assert here; the HTTP
        # status alone (already checked) is the source of truth.
        return

    statuses = [r.get("status") for r in results if isinstance(r, dict)]
    if not statuses or any(s == "ok" for s in statuses):
        return

    summary = ", ".join(
        f"{r.get('label', '?')}:{r.get('status', '?')}"
        for r in results
        if isinstance(r, dict)
    )
    raise LIFXError(f"no bulbs reachable ({summary})")


async def apply_effect(
    profile: Profile,
    *,
    token: str,
    selector: str,
    base_url: str = "https://api.lifx.com/v1",
) -> None:
    """POST a single LIFX effect call for the given profile.

    Endpoint: POST /lights/{selector}/effects/{effect}
    Docs: https://api.developer.lifx.com/reference/effects
    """
    # Lazy-imported so the pure helpers above can be unit-tested outside
    # the Cloudflare runtime (the `workers` module only exists inside it).
    from workers import fetch

    url = f"{base_url}/lights/{selector}/effects/{profile.effect}"
    body = json.dumps({
        "color": profile.color,
        "period": profile.period,
        "cycles": profile.cycles,
        "power_on": profile.power_on,
    })

    try:
        response = await fetch(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            body=body,
        )
    except Exception as exc:  # pyodide raises OSError on network failure
        raise LIFXError(f"network error talking to LIFX: {exc}") from exc

    if response.status >= 400:
        detail = await response.text()
        raise LIFXError(f"LIFX returned HTTP {response.status}: {detail[:200]}")

    try:
        payload = await response.json()
    except (ValueError, json.JSONDecodeError):
        return  # Non-JSON success body — nothing to inspect.

    _check_lifx_results(payload)
