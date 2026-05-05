"""Spiritolo: local-edit / staging-upload tooling.

Modules:
- ``tables`` — owned-tables list (single source of truth, also imported
  by Stage 3 utilities).
- ``sidecar`` — JSONC parser + jsonschema validation of the .meta.json.
- ``dump``   — pg_restore --list parsing, file/schema sha256.
- ``db``     — staging/local connection helpers, applied-migrations,
              max(updated_at), dirty-set queries.
- ``upsert`` — UPSERT SQL builder, sequence-resync SQL builder.
- ``cli``    — argparse + orchestration. Entry point is ``__main__``.
"""
