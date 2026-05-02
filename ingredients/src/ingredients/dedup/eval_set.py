"""Dedup eval cases. Drives both --review (CI) and ad-hoc spot-checks.

Each case fixes:
  - raw_name        : what the recipe is titled
  - ingredients     : (slug, amount, unit, position) tuples
  - expect_canonical: post-normalize_cocktail_name lookup result
  - expect_cluster_label : a label string; cases sharing the same label
                          must end up in the same cluster after compute.

The fixture taxonomy (eval_fixture.py) is the only DB state these cases
depend on. Run --review against TEST_DB_URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from .cluster import compute_cluster_key
from .eval_fixture import seed_dedup_fixture
from .normalize import normalize_cocktail_name
from .role_classifier import classify_role
from .rollup import roll_up_to_antichain


@dataclass(frozen=True)
class DedupEvalCase:
    raw_name: str
    ingredients: list[tuple[str, float, str, int]]   # (slug, amount, unit, position)
    expect_canonical: str
    expect_cluster_label: str


CASES: list[DedupEvalCase] = [
    DedupEvalCase(
        raw_name="Negroni",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",
    ),
    DedupEvalCase(
        raw_name="The Best Negroni Recipe",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",
    ),
    DedupEvalCase(
        raw_name="Negroni (Italian Aperitivo)",
        ingredients=[("london_dry_gin", 1.5, "oz", 1),  # different ratio, same cluster
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",
    ),
    DedupEvalCase(
        raw_name="Aperol Negroni",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("aperol",         1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="aperol negroni",
        expect_cluster_label="aperol-negroni",  # different cluster from negroni-classic
    ),
    DedupEvalCase(
        raw_name="Old Fashioned",
        ingredients=[("bourbon",            2.0, "oz",   1),
                     ("simple_syrup",       0.25, "oz",  2),
                     ("angostura_bitters",  2.0, "dash", 3)],
        expect_canonical="old fashioned",
        expect_cluster_label="old-fashioned-bourbon",
    ),
    DedupEvalCase(
        raw_name="Rye Old Fashioned",
        ingredients=[("rye_whiskey",        2.0, "oz",   1),
                     ("simple_syrup",       0.25, "oz",  2),
                     ("angostura_bitters",  2.0, "dash", 3)],
        expect_canonical="old fashioned",  # name still normalizes
        expect_cluster_label="old-fashioned-rye",  # but ingredient set differs
    ),
]


@dataclass
class EvalReport:
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def run_eval() -> EvalReport:
    """Run cases against TEST_DB_URL using the fixture."""
    import os
    import psycopg as pg

    test_db_url = os.environ.get("TEST_DB_URL")
    if not test_db_url:
        raise RuntimeError("TEST_DB_URL not set; eval requires fixture DB.")

    report = EvalReport()
    with pg.connect(test_db_url, autocommit=True) as conn:
        ids = seed_dedup_fixture(conn)

        labels: dict[str, str] = {}
        for case in CASES:
            try:
                _evaluate_case(conn, case, ids, labels)
                report.passed += 1
            except AssertionError as exc:
                report.failed += 1
                report.failures.append(f"{case.raw_name}: {exc}")

    if report.failures:
        for f in report.failures:
            print("FAIL:", f)
    print(f"\n{report.passed} passed, {report.failed} failed.")
    return report


def _evaluate_case(
    conn: psycopg.Connection,
    case: DedupEvalCase,
    ids: dict[str, int],
    labels: dict[str, str],
) -> None:
    # 1. Name normalization expectation.
    normalized = normalize_cocktail_name(case.raw_name)
    row = conn.execute(
        "select canonical_name from cocktail_aliases where alias = %s",
        (normalized,),
    ).fetchone()
    canonical = row[0] if row else None
    assert canonical == case.expect_canonical, (
        f"name normalization: got {canonical!r}, expected {case.expect_canonical!r}"
    )

    # 2. Build the ingredient list with role + antichain rollup.
    ings = []
    for slug, amount, unit, pos in case.ingredients:
        node_id = ids[slug]
        node_row = conn.execute(
            "select default_role, is_defining_garnish from taxonomy_nodes where id = %s",
            (node_id,),
        ).fetchone()
        default_role, is_def_garnish = node_row
        ing = {
            "taxonomy_node_slug": slug, "taxonomy_node_id": node_id,
            "default_role": default_role, "is_defining_garnish": is_def_garnish,
            "amount": amount, "unit": unit, "position": pos, "raw_text": "",
        }
        role, _ = classify_role(ing)
        ing["role"] = role
        ing["antichain_node_id"] = roll_up_to_antichain(conn, node_id)
        ings.append(ing)

    # 3. Cluster key expectation.
    cluster_key = compute_cluster_key(case.expect_canonical, ings)
    if case.expect_cluster_label in labels:
        assert labels[case.expect_cluster_label] == cluster_key, (
            f"cluster mismatch for label {case.expect_cluster_label}: "
            f"got {cluster_key[:8]}…, expected {labels[case.expect_cluster_label][:8]}…"
        )
    else:
        labels[case.expect_cluster_label] = cluster_key
