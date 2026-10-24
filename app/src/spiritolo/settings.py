"""Process configuration, read from the environment once at startup.

Non-secret values are plain Railway variables; secrets arrive through
``op run --env-file secrets.env`` (1Password) and are only ever read here.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DB = "data/spiritolo.db"


@dataclass(frozen=True)
class Settings:
    db_path: str = DEFAULT_DB
    # The origin browsers use to reach the app; the WebAuthn relying-party id
    # is its hostname and the session cookie is `Secure` when it is https.
    public_origin: str = "http://localhost:8000"
    rp_name: str = "Spiritolo"
    session_secret: str = ""
    session_max_age: int = 30 * 24 * 3600
    static_dir: str | None = None
    run_executor: bool = True
    executor_poll_seconds: float = 5.0
    # Any extra origins (e.g. the Vite dev server) allowed as WebAuthn
    # origins and for CORS with credentials.
    extra_origins: tuple[str, ...] = field(default_factory=tuple)
    # How `POST /api/ops/import-db/apply` takes effect: exit the process and
    # let the supervisor's entrypoint swap the staged file in (the container
    # shape, where Litestream must see the swap from a cold start), or swap
    # in place and reopen (local runs with no supervisor).
    import_restart: bool = False

    @property
    def rp_id(self) -> str:
        return urlparse(self.public_origin).hostname or "localhost"

    @property
    def secure_cookies(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def origins(self) -> list[str]:
        return [self.public_origin, *self.extra_origins]


def from_env(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    secret = e.get("SESSION_SECRET") or ""
    if not secret:
        # Sessions then die with the process. Fine for local dev; the deploy
        # always sets SESSION_SECRET through the vault.
        secret = secrets.token_urlsafe(48)
    static = e.get("STATIC_DIR")
    if static is None:
        guess = Path(__file__).resolve().parents[3] / "web" / "dist"
        static = str(guess) if guess.is_dir() else None
    extra = tuple(o.strip() for o in e.get("EXTRA_ORIGINS", "").split(",") if o.strip())
    return Settings(
        db_path=e.get("SPIRITOLO_DB", DEFAULT_DB),
        public_origin=(e.get("PUBLIC_ORIGIN") or "http://localhost:8000").rstrip("/"),
        rp_name=e.get("RP_NAME", "Spiritolo"),
        session_secret=secret,
        static_dir=static,
        run_executor=e.get("RUN_EXECUTOR", "1") not in ("0", "false", "no"),
        executor_poll_seconds=float(e.get("EXECUTOR_POLL_SECONDS", "5")),
        extra_origins=extra,
        import_restart=e.get("IMPORT_RESTART", "0") not in ("0", "false", "no", ""),
    )
