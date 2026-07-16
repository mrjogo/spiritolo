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


# --------------------------------------------------------------------------- #
# deploy-migrations.yml — the PR-to-main validate gate                          #
# --------------------------------------------------------------------------- #

def _all_run_scripts(job: dict) -> str:
    return "\n".join(
        step.get("run", "") for step in job.get("steps", []) if isinstance(step, dict)
    )


def test_deploy_migrations_has_validate_job():
    doc = _yaml(".github/workflows/deploy-migrations.yml")
    on = _on(doc)
    pr = on["pull_request"]
    assert "main" in pr["branches"]
    assert "supabase/migrations/**" in pr["paths"]

    # A job that runs a postgres:16 service and forward-applies every migration
    # with ON_ERROR_STOP.
    validate = next(
        (
            j for j in doc["jobs"].values()
            if isinstance(j.get("services"), dict)
            and any(
                str(svc.get("image", "")).startswith("postgres:16")
                for svc in j["services"].values()
            )
        ),
        None,
    )
    assert validate is not None, "no validate job with a postgres:16 service"
    script = _all_run_scripts(validate)
    assert "ON_ERROR_STOP=1" in script
    assert "supabase/migrations/*.sql" in script
    assert "psql" in script


def test_deploy_migrations_no_rebuild_projections():
    # The single-DB topology gives main a validation gate only; no projection
    # rebuild step is wired here.
    doc = _text(".github/workflows/deploy-migrations.yml")
    assert "rebuild_projections" not in doc


# --------------------------------------------------------------------------- #
# web-ci.yml — the Vitest PR gate for the SPA                                   #
# --------------------------------------------------------------------------- #

def test_web_ci_runs_vitest():
    doc = _yaml(".github/workflows/web-ci.yml")
    on = _on(doc)
    assert "web/**" in on["pull_request"]["paths"]

    job = next(iter(doc["jobs"].values()))
    script = _all_run_scripts(job)
    wd = job.get("defaults", {}).get("run", {}).get("working-directory", "")
    step_wds = [s.get("working-directory", "") for s in job.get("steps", []) if isinstance(s, dict)]
    in_web = wd == "web" or "web" in step_wds or "cd web" in script
    assert in_web, "web CI must run inside web/"
    assert "npm test" in script


# --------------------------------------------------------------------------- #
# railway.json — declarative Dockerfile builder, single replica                 #
# --------------------------------------------------------------------------- #

def test_railway_json_dockerfile_builder():
    cfg = json.loads(_text("railway.json"))
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["build"]["dockerfilePath"] == "worker.Dockerfile"
    assert cfg["deploy"]["numReplicas"] == 1
    assert cfg["deploy"]["restartPolicyType"] == "ON_FAILURE"


# --------------------------------------------------------------------------- #
# docs/devops-runbook.md — zero-to-deployed operator guide                      #
# --------------------------------------------------------------------------- #

def test_runbook_covers_all_steps():
    md = _text("docs/devops-runbook.md")
    lowered = md.lower()
    for marker in (
        "supabase pro",
        "repo secrets",
        "storage bucket",
        "tailscale",
        "railway",
        "vercel",
        "recipegf",
        "smoke",
        "promote",
    ):
        assert marker in lowered, f"runbook missing a section for {marker!r}"
    # The load-bearing secrets/artifacts an operator must not miss.
    assert "RECIPEGF_TOKEN" in md
    assert "TAILSCALE_AUTHKEY" in md
    assert "S3_" in md
    assert "v0.4.0" in md
    # No projection-rebuild step leaks into the runbook either.
    assert "rebuild_projections" not in md


# --------------------------------------------------------------------------- #
# workflows-ci.yml — this very shape test runs in CI (else it never guards)      #
# --------------------------------------------------------------------------- #

def test_shape_tests_gated_in_ci():
    doc = _yaml(".github/workflows/workflows-ci.yml")
    on = _on(doc)
    assert "main" in on["pull_request"]["branches"]
    # It must re-run when any artifact it inspects — or the test itself — changes.
    paths = set(on["pull_request"]["paths"])
    assert ".github/workflows/**" in paths

    job = next(iter(doc["jobs"].values()))
    script = _all_run_scripts(job)
    assert "pyyaml" in script.lower(), "the job must install PyYAML"
    assert "test_workflow_shapes.py" in script, "the job must run the shape test"
