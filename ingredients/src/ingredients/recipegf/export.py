"""Export orchestrator: drain the cluster export queue into validated pin-2
bundles (persisted onto the cluster + optionally written as JSON files), and
park anything the converter can't emit into ``recipegf_proposals``.

Kept separate from the CLI so it is exercisable against a real test DB in one
call. Pure orchestration over a psycopg connection + the pure converter.
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

    ``imported_at`` is the ISO-8601 stamp embedded in every bundle's meta
    (injected so the caller controls it — real time from the CLI, a fixed value
    from tests). ``dry_run`` suppresses all DB writes; ``out_dir`` (if set)
    writes ``<slug>.json`` files even under dry-run, as a preview artifact.
    """
    counts: Counter = Counter()
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    queue = export_db.fetch_export_queue(
        conn, converter_version=CONVERTER_VERSION, site=site, limit=limit
    )
    for row in queue:
        source = export_db.build_source_recipe(conn, row)
        result = convert_recipe(source)

        if isinstance(result, Uncertain):
            counts[result.reason] += 1
            if not dry_run:
                enqueue_proposal(
                    conn,
                    cluster_id=row["cluster_id"],
                    canonical_name=row["canonical_name"],
                    proposed_slug=None,
                    reason=result.reason,
                    detail=result.detail,
                    source_url=row["source_url"],
                    converter_version=CONVERTER_VERSION,
                )
                export_db.park_uncertain(
                    conn,
                    cluster_id=row["cluster_id"],
                    proposed_slug=None,
                    source=row["source_url"] or "",
                    converter_version=CONVERTER_VERSION,
                )
                conn.commit()
            continue

        assert isinstance(result, Ok)
        bundle = build_bundle(
            result.recipe,
            verb_defs_for(result.spiritolo_verbs),
            slug=result.slug,
            source=row["source_url"] or "",
            imported_at=imported_at,
        )
        counts["exported"] += 1

        if out_path is not None:
            (out_path / f"{result.slug}.json").write_text(
                json.dumps(bundle, indent=2) + "\n", encoding="utf-8"
            )
            counts["files"] += 1

        if not dry_run:
            export_db.write_bundle(
                conn,
                cluster_id=row["cluster_id"],
                slug=result.slug,
                bundle=bundle,
                source=row["source_url"] or "",
                converter_version=CONVERTER_VERSION,
            )
            conn.commit()

    return counts
