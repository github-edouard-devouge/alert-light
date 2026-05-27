"""Shared pytest fixtures.

The default test suite is pure Python: it imports `profiles` directly.

The optional integration suite (marker: `integration`) talks to a running
Worker. It picks a server in this order:

1. `ALERT_LIGHT_DEV_URL` env var, e.g. `http://127.0.0.1:8787` — used as-is.
2. An existing `pywrangler dev` already listening on `127.0.0.1:8787`
   (auto-detected) — reused, not respawned.
3. Otherwise, spawn a fresh `pywrangler dev` on a free port for the test
   session and tear it down at the end.

This makes the tests usable in three scenarios: CI (auto-spawn), local
development (reuse the `make dev` server you already have running), and
explicit override (point at any URL, e.g. a staging Worker).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEV_PORT = 8787


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_worker_listening(url: str, timeout: float = 1.0) -> bool:
    """Return True if `url`/health responds with HTTP 200 within `timeout`."""
    try:
        with urlopen(f"{url}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


@contextmanager
def _pywrangler_dev():
    """Spawn `pywrangler dev` in the project root and yield its base URL."""
    if shutil.which("pywrangler") is None and shutil.which("uv") is None:
        pytest.skip("neither pywrangler nor uv found on PATH")

    port = _find_free_port()
    cmd = (
        ["pywrangler"] if shutil.which("pywrangler") else ["uv", "run", "pywrangler"]
    ) + ["dev", "--port", str(port)]

    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 120  # first run downloads pyodide, can be slow
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("pywrangler exited before becoming ready")
            if _is_worker_listening(base_url, timeout=0.5):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("pywrangler dev did not become ready in 120s")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def webhook_secret() -> str:
    """Read SHARED_SECRET from .dev.vars; skip the test if absent.

    Integration tests that need to authenticate against the Worker use
    this fixture so they target the same secret pywrangler dev loaded
    into the running server.
    """
    override = os.environ.get("ALERT_LIGHT_SHARED_SECRET")
    if override:
        return override

    dev_vars = REPO_ROOT / ".dev.vars"
    if not dev_vars.exists():
        pytest.skip(".dev.vars not found — set SHARED_SECRET to run this test")

    for line in dev_vars.read_text().splitlines():
        line = line.strip()
        if line.startswith("SHARED_SECRET="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value

    pytest.skip(".dev.vars does not define SHARED_SECRET")


@pytest.fixture(scope="session")
def dev_server():
    """Yield the base URL of a running Worker (reused or spawned)."""
    override = os.environ.get("ALERT_LIGHT_DEV_URL")
    if override:
        if not _is_worker_listening(override, timeout=2.0):
            pytest.skip(f"ALERT_LIGHT_DEV_URL={override} is not responding")
        yield override.rstrip("/")
        return

    default_url = f"http://127.0.0.1:{DEFAULT_DEV_PORT}"
    if _is_worker_listening(default_url, timeout=0.5):
        yield default_url
        return

    with _pywrangler_dev() as base_url:
        yield base_url
