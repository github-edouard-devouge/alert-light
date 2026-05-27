"""Mapping from Datadog alert_type -> visual effect on the LIFX bulb.

Pure module: no Worker / network dependencies, safe to import from tests.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """A LIFX effect parametrisation for a given semantic alert state."""

    name: str
    effect: str
    color: str
    period: float
    cycles: int
    power_on: bool = True


_PROFILES: dict[str, Profile] = {
    "error":   Profile("error",   "pulse",   "red",    0.6, 12),
    "warning": Profile("warning", "pulse",   "orange", 0.8, 8),
    "success": Profile("success", "breathe", "green",  1.5, 3),
    "info":    Profile("info",    "breathe", "blue",   2.0, 2),
    "no_data": Profile("no_data", "breathe", "purple", 1.5, 3),
}


def get_profile(alert_type: str | None, transition: str | None) -> Profile | None:
    """Resolve the profile to play for a Datadog event.

    A `transition` of "Recovered" always wins and plays the success profile,
    regardless of the original alert_type. Lookup is case-insensitive.
    Returns None for unknown alert types so callers can ignore them.
    """
    if transition and transition.strip().lower() == "recovered":
        return _PROFILES["success"]

    if not alert_type:
        return None

    return _PROFILES.get(alert_type.strip().lower())


def all_profiles() -> dict[str, Profile]:
    """Return a defensive copy of the profile catalogue (used in tests)."""
    return dict(_PROFILES)
