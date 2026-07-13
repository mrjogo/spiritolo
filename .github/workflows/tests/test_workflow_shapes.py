"""Shape tests for the deploy artifacts — CI YAML, railway.json, the worker
Dockerfile + entrypoint, and the setup runbook.

These parse the committed files as text / YAML / JSON and assert the wiring that
makes the fully-cloud topology deploy correctly: the migration validate gate,
the web Vitest gate, the Railway worker deploy, the userspace-Tailscale image,
and a runbook that takes an operator zero-to-deployed. No processes are run.

Run from the ingredients uv env (which carries PyYAML + pytest)::

    cd ingredients && uv run --extra dev python -m pytest \
        ../.github/workflows/tests/test_workflow_shapes.py
"""
from __future__ import annotations

import json
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"


def _text(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"missing file: {rel}"
    return path.read_text()


def _yaml(rel: str) -> dict:
    return yaml.safe_load(_text(rel))


def _on(doc: dict) -> dict:
    # PyYAML parses the bare key ``on`` as the boolean True.
    return doc.get("on", doc.get(True))


# --------------------------------------------------------------------------- #
# worker.Dockerfile — userspace Tailscale, no privileged networking            #
# --------------------------------------------------------------------------- #

def test_dockerfile_userspace_no_privileged():
    df = _text("worker.Dockerfile")
    # Static Tailscale binaries copied from the official image.
    assert "tailscale/tailscale:stable" in df
    assert "/usr/local/bin/tailscaled" in df
    assert "/usr/local/bin/tailscale" in df
    # Userspace pattern: no privileged networking anywhere.
    assert "NET_ADMIN" not in df
    assert "/dev/net/tun" not in df
    assert "--privileged" not in df
    # Frozen install of the worker package.
    assert "uv sync --frozen" in df
    assert "--package spiritolo-ingredients" in df
    # RECIPEGF_TOKEN is a build ARG, never a runtime ENV.
    assert "ARG RECIPEGF_TOKEN" in df
    assert "ENV RECIPEGF_TOKEN" not in df
    assert "python:3.11-slim" in df


# --------------------------------------------------------------------------- #
# scripts/worker-entrypoint.sh — tailscaled userspace + ephemeral join + exec  #
# --------------------------------------------------------------------------- #

def test_entrypoint_starts_tailscaled_userspace():
    sh = _text("scripts/worker-entrypoint.sh")
    assert "tailscaled" in sh
    assert "--tun=userspace-networking" in sh
    assert "--socks5-server=localhost:1055" in sh
    assert "--state=mem:" in sh


def test_entrypoint_joins_ephemeral_authkey():
    sh = _text("scripts/worker-entrypoint.sh")
    assert "set -euo pipefail" in sh, "needs set -u so the :? guard fires"
    assert "tailscale up" in sh
    assert "TAILSCALE_AUTHKEY" in sh
    assert ":?" in sh, "required-var guard on TAILSCALE_AUTHKEY"
    assert "--hostname=" in sh and "spiritolo-worker" in sh


def test_entrypoint_execs_worker():
    sh = _text("scripts/worker-entrypoint.sh")
    lines = [ln.strip() for ln in sh.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert lines[-1] == (
        "exec uv run --package spiritolo-ingredients python -m ingredients.worker"
    ), "final line must exec the worker (PID-1 handoff)"


def test_entrypoint_no_global_proxy_export():
    # Only TS_LOCAL_PROXY is exported; a global ALL_PROXY/HTTPS_PROXY would
    # tunnel hosted APIs through barbot's uplink.
    sh = _text("scripts/worker-entrypoint.sh")
    assert "export TS_LOCAL_PROXY=" in sh
    assert "export ALL_PROXY" not in sh
    assert "export HTTPS_PROXY" not in sh
