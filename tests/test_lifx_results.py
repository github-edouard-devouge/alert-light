"""Unit tests for the LIFX results parser.

These exercise `_check_lifx_results` in isolation — the pure-Python helper
that turns a `results[]` payload into either silent success or LIFXError.
The async `apply_effect` orchestration is covered by integration tests.
"""
from __future__ import annotations

import pytest

from lifx_client import LIFXError, _check_lifx_results


def test_all_bulbs_ok_returns_silently():
    payload = {"results": [
        {"id": "a", "label": "Alert-Light", "status": "ok"},
    ]}
    _check_lifx_results(payload)  # no exception


def test_multi_bulb_all_ok_returns_silently():
    payload = {"results": [
        {"id": "a", "label": "one", "status": "ok"},
        {"id": "b", "label": "two", "status": "ok"},
    ]}
    _check_lifx_results(payload)


def test_all_offline_raises():
    payload = {"results": [
        {"id": "a", "label": "Alert-Light", "status": "offline"},
    ]}
    with pytest.raises(LIFXError, match="no bulbs reachable"):
        _check_lifx_results(payload)


def test_all_timed_out_raises():
    payload = {"results": [
        {"id": "a", "label": "Alert-Light", "status": "timed_out"},
    ]}
    with pytest.raises(LIFXError, match="timed_out"):
        _check_lifx_results(payload)


def test_mixed_offline_and_ok_returns_silently():
    """Partial success — at least one bulb received the effect. Don't fail."""
    payload = {"results": [
        {"id": "a", "label": "one", "status": "offline"},
        {"id": "b", "label": "two", "status": "ok"},
    ]}
    _check_lifx_results(payload)


def test_all_offline_error_includes_each_bulb_label():
    payload = {"results": [
        {"id": "a", "label": "Lamp-1", "status": "offline"},
        {"id": "b", "label": "Lamp-2", "status": "timed_out"},
    ]}
    with pytest.raises(LIFXError) as excinfo:
        _check_lifx_results(payload)
    msg = str(excinfo.value)
    assert "Lamp-1:offline" in msg
    assert "Lamp-2:timed_out" in msg


def test_empty_results_list_returns_silently():
    """No bulbs matched the selector — surfaced by HTTP status, not here."""
    _check_lifx_results({"results": []})


def test_missing_results_key_returns_silently():
    """Endpoints that don't return per-bulb status are not our concern."""
    _check_lifx_results({"some_other_key": 1})


def test_non_dict_payload_returns_silently():
    _check_lifx_results(["unexpected"])
    _check_lifx_results(None)
    _check_lifx_results("string-payload")
