"""Shape tests for the deploy artifacts — CI YAML, railway.json, the service
Dockerfile + entrypoint, litestream.yml, secrets.env, and the setup runbook.

These parse the committed files as text / YAML / JSON and assert the wiring that
makes the one-service Railway topology deploy correctly: the Python and web PR
gates, the Dockerfile builder, the Litestream-wrapped entrypoint, 1Password
secrets by reference only, and a runbook that takes an operator zero-to-deployed.
No processes are run.

Run from the ingredients uv env (which carries PyYAML + pytest)::

    cd ingredients && uv run --extra dev python -m pytest \
        ../.github/workflows/tests/test_workflow_shapes.py
"""
from __future__ import annotations

import json
import pathlib
import re

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


def _all_run_scripts(job: dict) -> str:
    return "\n".join(
        step.get("run", "") for step in job.get("steps", []) if isinstance(step, dict)
    )


# --------------------------------------------------------------------------- #
# Dockerfile — web build + python runtime, secrets never baked in              #
# --------------------------------------------------------------------------- #

def test_dockerfile_builds_web_and_runtime():
    df = _text("Dockerfile")
    assert "FROM node:20-slim AS web" in df
    assert "npm run build" in df
    assert "python:3.11-slim" in df
    assert "COPY --from=web /web/dist /app/web/dist" in df
    # Frozen install of the service package.
    assert "uv sync --frozen" in df
    assert "--package spiritolo-app" in df


def test_dockerfile_ships_litestream_op_and_userspace_tailscale():
    df = _text("Dockerfile")
    assert "litestream/litestream:" in df
    assert "1password/op:" in df
    assert "tailscale/tailscale:stable" in df
    # Userspace pattern: no privileged networking anywhere.
    assert "NET_ADMIN" not in df
    assert "/dev/net/tun" not in df
    assert "--privileged" not in df


def test_dockerfile_bakes_no_secrets():
    df = _text("Dockerfile")
    # RECIPEGF_TOKEN is a build ARG, never a runtime ENV.
    assert "ARG RECIPEGF_TOKEN" in df
    assert "ENV RECIPEGF_TOKEN" not in df
    for name in ("OP_SERVICE_ACCOUNT_TOKEN", "SESSION_SECRET", "LITESTREAM_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        assert name not in df, f"{name} must come from the vault at boot, not the image"
    # The entrypoint and the secrets template are copied in; the runtime env
    # points at the volume and turns on restart-mode import.
    assert "COPY secrets.env /app/secrets.env" in df
    assert "COPY scripts/entrypoint.sh" in df
    assert "SPIRITOLO_DB=/data/spiritolo.db" in df
    assert "IMPORT_RESTART=1" in df


# --------------------------------------------------------------------------- #
# scripts/entrypoint.sh — staged import, op run, litestream restore + replicate #
# --------------------------------------------------------------------------- #

def test_entrypoint_runs_under_op_when_token_present():
    sh = _text("scripts/entrypoint.sh")
    assert "set -euo pipefail" in sh
    assert "OP_SERVICE_ACCOUNT_TOKEN" in sh
    assert "op run --env-file /app/secrets.env" in sh


def test_entrypoint_applies_staged_import_before_anything_opens_the_db():
    sh = _text("scripts/entrypoint.sh")
    swap = sh.index('"$DB_PATH.import"')
    assert swap < sh.index("litestream restore"), "the import swap must precede the Litestream restore"
    assert swap < sh.index("litestream replicate")
    assert 'rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"' in sh


def test_entrypoint_derives_litestream_settings_from_the_attached_bucket():
    sh = _text("scripts/entrypoint.sh")
    assert 'LITESTREAM_REPLICA_URL="s3://${BUCKET_NAME}/spiritolo"' in sh
    for var in ("BUCKET_ENDPOINT", "BUCKET_REGION", "BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"):
        assert var in sh


def test_entrypoint_restores_then_replicates_with_uvicorn_as_child():
    sh = _text("scripts/entrypoint.sh")
    assert "litestream restore -if-replica-exists" in sh
    assert "litestream replicate -config /etc/litestream.yml" in sh
    assert "-exec" in sh
    assert "uvicorn spiritolo.main:app --factory" in sh
    assert "--host 0.0.0.0" in sh
    # Without a replica URL it still boots (local docker runs).
    assert "LITESTREAM_REPLICA_URL" in sh


def test_entrypoint_tailscale_is_optional_and_userspace():
    sh = _text("scripts/entrypoint.sh")
    assert 'if [ -n "${TAILSCALE_AUTHKEY:-}" ]' in sh
    assert "--tun=userspace-networking" in sh
    assert "--socks5-server=localhost:1055" in sh
    assert "--state=mem:" in sh
    # Only TS_LOCAL_PROXY is exported; a global ALL_PROXY/HTTPS_PROXY would
    # tunnel hosted APIs through the tailnet uplink.
    assert "export TS_LOCAL_PROXY=" in sh
    assert "export ALL_PROXY" not in sh
    assert "export HTTPS_PROXY" not in sh


# --------------------------------------------------------------------------- #
# litestream.yml + secrets.env — everything by reference, nothing literal      #
# --------------------------------------------------------------------------- #

def test_litestream_config_reads_everything_from_env():
    cfg = _text("litestream.yml")
    for var in ("SPIRITOLO_DB", "LITESTREAM_REPLICA_URL", "LITESTREAM_ENDPOINT", "LITESTREAM_REGION",
                "LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY"):
        assert "${" + var + "}" in cfg, f"litestream.yml must read {var} from the environment"
    doc = yaml.safe_load(cfg)
    replica = doc["dbs"][0]["replicas"][0]
    assert replica["type"] == "s3" and replica["force-path-style"] is True
    assert "retention" in replica and "snapshot-interval" in replica


def test_secrets_env_holds_only_op_references():
    env = _text("secrets.env")
    for line in env.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        assert re.fullmatch(r"[A-Z0-9_]+", name), f"odd variable name {name!r}"
        assert value.startswith("op://"), f"{name} must be an op:// reference, got {value!r}"
    names = {ln.partition("=")[0] for ln in env.splitlines() if ln and not ln.startswith("#")}
    assert "SESSION_SECRET" in names
    # Bucket credentials are Railway reference variables, never vault items.
    for name in ("LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY",
                 "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        assert name not in names, f"{name} must come from the attached Railway bucket, not the vault"


# --------------------------------------------------------------------------- #
# railway.json — declarative Dockerfile builder, health-checked single replica #
# --------------------------------------------------------------------------- #

def test_railway_json_dockerfile_builder():
    cfg = json.loads(_text("railway.json"))
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["build"]["dockerfilePath"] == "Dockerfile"
    assert cfg["deploy"]["numReplicas"] == 1
    assert cfg["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert cfg["deploy"]["healthcheckPath"] == "/api/health"


# --------------------------------------------------------------------------- #
# python-ci.yml / web-ci.yml — the PR gates                                     #
# --------------------------------------------------------------------------- #

def test_python_ci_runs_every_suite_without_a_database_service():
    doc = _yaml(".github/workflows/python-ci.yml")
    on = _on(doc)
    assert "main" in on["pull_request"]["branches"]
    paths = set(on["pull_request"]["paths"])
    assert {"app/**", "common/**", "ingredients/**", "scripts/**", "uv.lock"} <= paths
    job = next(iter(doc["jobs"].values()))
    assert "services" not in job, "SQLite suites need no database service"
    script = _all_run_scripts(job)
    assert "uv sync --frozen --all-packages --all-extras" in script
    for member in ("common", "ingredients", "app", "scripts"):
        assert f"cd {member} && uv run --no-sync pytest" in script


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


def test_no_supabase_deploy_workflows_remain():
    names = {p.name for p in WORKFLOWS.glob("*.yml")}
    assert "deploy-migrations.yml" not in names
    assert "keepalive.yml" not in names


# --------------------------------------------------------------------------- #
# docs/devops-runbook.md — zero-to-deployed operator guide                      #
# --------------------------------------------------------------------------- #

def test_runbook_covers_all_steps():
    md = _text("docs/devops-runbook.md")
    lowered = md.lower()
    for marker in (
        "railway",
        "volume",
        "bucket",
        "1password",
        "litestream",
        "passkey",
        "deploy branch",
        "recipegf",
        "smoke",
        "import",
    ):
        assert marker in lowered, f"runbook missing a section for {marker!r}"
    # The load-bearing variables an operator must not miss.
    for var in ("OP_SERVICE_ACCOUNT_TOKEN", "PUBLIC_ORIGIN", "BUCKET_NAME",
                "BUCKET_ACCESS_KEY_ID", "AWS_ENDPOINT_URL", "AWS_S3_BUCKET_NAME"):
        assert var in md, f"runbook must name {var}"
    # Nothing from the Supabase era leaks back in.
    assert "supabase db push" not in lowered
    assert "vercel" not in lowered


# --------------------------------------------------------------------------- #
# workflows-ci.yml — this very shape test runs in CI (else it never guards)      #
# --------------------------------------------------------------------------- #

def test_shape_tests_gated_in_ci():
    doc = _yaml(".github/workflows/workflows-ci.yml")
    on = _on(doc)
    assert "main" in on["pull_request"]["branches"]
    # It must re-run when any artifact it inspects — or the test itself — changes.
    paths = set(on["pull_request"]["paths"])
    assert {".github/workflows/**", "Dockerfile", "scripts/entrypoint.sh", "railway.json",
            "litestream.yml", "secrets.env", "docs/devops-runbook.md"} <= paths

    job = next(iter(doc["jobs"].values()))
    script = _all_run_scripts(job)
    assert "pyyaml" in script.lower(), "the job must install PyYAML"
    assert "test_workflow_shapes.py" in script, "the job must run the shape test"
