"""Export orchestrator: drain the cluster export queue, persisting each drink's
verb-frame recipe **relationally** (``recipegf_recipes`` + ``_ingredients`` +
``_steps``) and parking anything the converter can't emit into
``recipegf_proposals``.

The pin-2 bundle is a *projection* of those rows — generated on demand by
:func:`ingredients.recipegf.db.generate_bundle` — not a stored blob. Kept
separate from the CLI so it is exercisable against a real test DB in one call.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg

from . import db as export_db
from .bundle import build_bundle
from .converter import Ok, Uncertain, convert_recipe
from .proposals import enqueue_proposal
from .verbs import verb_defs_for
from .version import CONVERTER_VERSION

log = logging.getLogger("recipegf_export")


def run_export(
    conn: psycopg.Connection,
    *,
    imported_at: str,
    site: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    out_dir: str | Path | None = None,
) -> Counter:
    """Process the export queue. Returns a Counter of outcomes: ``exported``,
    each Uncertain ``reason`` code, and ``files`` (bundles written to disk).

    Every ``Ok`` is validated + seam-checked (via :func:`build_bundle`) before
    it is persisted, so an invalid recipe never lands. ``dry_run`` suppresses
    all DB writes; ``out_dir`` writes ``<slug>.json`` — generated from the
    stored rows when persisted, or from the in-memory bundle under ``dry_run``
    (a preview; its ``imported_at`` is the passed value rather than the row's
    ``exported_at``).
    """
    counts: Counter = Counter()
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    # Keep the DB copy of the in-repo spiritolo/ verb-defs fresh, so the
    # recipegf_bundle RPC returns a self-contained bundle. Refresh before
    # draining the queue so any exported row's verbs are already present.
    if not dry_run:
        export_db.sync_verb_defs(conn)
        conn.commit()

    queue = export_db.fetch_export_queue(
        conn, converter_version=CONVERTER_VERSION, site=site, limit=limit
    )
    for row in queue:
        cluster_id = row["cluster_id"]
        source = export_db.build_source_recipe(conn, row)
        result = convert_recipe(source)

        if isinstance(result, Uncertain):
            counts[result.reason] += 1
            if not dry_run:
                enqueue_proposal(
                    conn,
                    cluster_id=cluster_id,
                    canonical_name=row["canonical_name"],
                    proposed_slug=None,
                    reason=result.reason,
                    detail=result.detail,
                    source_url=row["source_url"],
                    converter_version=CONVERTER_VERSION,
                )
                export_db.park_uncertain(
                    conn,
                    cluster_id=cluster_id,
                    proposed_slug=None,
                    source=row["source_url"] or "",
                    converter_version=CONVERTER_VERSION,
                )
                conn.commit()
            continue

        assert isinstance(result, Ok)
        # Validate + enforce the seam guarantees before persisting (raises on
        # violation, so an invalid recipe can never be stored).
        preview_bundle = build_bundle(
            result.recipe,
            verb_defs_for(result.spiritolo_verbs),
            slug=result.slug,
            source=row["source_url"] or "",
            imported_at=imported_at,
        )
        counts["exported"] += 1

        bundle_for_file: dict[str, Any] = preview_bundle
        if not dry_run:
            export_db.write_recipe(
                conn,
                cluster_id=cluster_id,
                result=result,
                source=row["source_url"] or "",
                converter_version=CONVERTER_VERSION,
            )
            conn.commit()
            # Canonical path: the emitted bundle is generated from the stored
            # relational rows, not the in-memory dict.
            bundle_for_file = export_db.generate_bundle(
                conn, cluster_id=cluster_id, converter_version=CONVERTER_VERSION
            )

        if out_path is not None:
            (out_path / f"{result.slug}.json").write_text(
                json.dumps(bundle_for_file, indent=2) + "\n", encoding="utf-8"
            )
            counts["files"] += 1

    return counts
