"""Unit tests for the alert_type -> Profile mapping.

These tests are pure Python and do NOT require the Cloudflare runtime —
they run with plain pytest.
"""
from __future__ import annotations

import pytest

from profiles import Profile, all_profiles, get_profile


def test_error_alert_type_maps_to_red_pulse():
    profile = get_profile("error", "Triggered")
    assert profile is not None
    assert profile.name == "error"
    assert profile.effect == "pulse"
    assert profile.color == "red"


def test_warning_alert_type_maps_to_orange_pulse():
    profile = get_profile("warning", "Triggered")
    assert profile is not None
    assert profile.color == "orange"
    assert profile.effect == "pulse"


def test_info_alert_type_maps_to_blue_breathe():
    profile = get_profile("info", "Triggered")
    assert profile is not None
    assert profile.effect == "breathe"
    assert profile.color == "blue"


def test_no_data_alert_type_maps_to_purple_breathe():
    profile = get_profile("no_data", "Triggered")
    assert profile is not None
    assert profile.color == "purple"


@pytest.mark.parametrize("alert_type", ["error", "warning", "info", "no_data"])
def test_recovered_transition_always_wins(alert_type):
    """Any Recovered transition plays the success profile, regardless of type."""
    profile = get_profile(alert_type, "Recovered")
    assert profile is not None
    assert profile.name == "success"
    assert profile.color == "green"


def test_lookup_is_case_insensitive():
    assert get_profile("ERROR", "TRIGGERED") == get_profile("error", "triggered")
    assert get_profile("  Warning  ", "Triggered") == get_profile("warning", "Triggered")


def test_unknown_alert_type_returns_none():
    assert get_profile("mystery", "Triggered") is None


def test_none_alert_type_returns_none():
    assert get_profile(None, "Triggered") is None


def test_all_profiles_returns_independent_copy():
    snapshot = all_profiles()
    snapshot["error"] = Profile("error", "noop", "black", 0, 0)
    assert get_profile("error", "Triggered").color == "red"


def test_profile_is_immutable():
    p = get_profile("error", "Triggered")
    with pytest.raises((AttributeError, Exception)):
        p.color = "blue"  # type: ignore[misc]
