"""parse_ingredients CLI.

Modes:
  --review                run the eval set, print pass/fail, exit 0 on green.
  (no flags)              run the polling worker. Implemented in a later task.

Shared options (added in a later task) match the scraper conventions:
  --site / --limit / --dry-run / --reset --yes / --except-version / --older-than
"""

from __future__ import annotations

import argparse
import sys

from ingredients.eval_set import run_eval


def run_review() -> int:
    result = run_eval()
    print(f"--- Parser eval ---")
    print(f"  passed: {result['passed']}")
    print(f"  failed: {result['failed']}")
    if result["failed"]:
        print()
        print("Failures:")
        for case in result["cases"]:
            if case["ok"]:
                continue
            r = case["result"]
            print(
                f"  {case['raw']!r}\n"
                f"    -> status={r.parse_status} rule={r.parser_rule} "
                f"amount={r.amount} amount_max={r.amount_max} "
                f"unit={r.unit} name={r.name!r}"
            )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="parse_ingredients",
        description="Spiritolo ingredient parser — Zone-2 reconciling worker.",
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Run the eval set against the parser; do not touch the database.",
    )
    args = parser.parse_args()
    if args.review:
        return run_review()
    parser.error("worker mode not yet implemented; pass --review for now")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
