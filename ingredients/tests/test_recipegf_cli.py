"""CLI wiring for recipegf-export. Pure-Python (no DB)."""

from __future__ import annotations

from ingredients.cli import build_arg_parser, run_recipegf_export


def test_export_subcommand_args():
    p = build_arg_parser()
    args = p.parse_args([
        "recipegf-export", "--site", "punch", "--limit", "5",
        "--dry-run", "--out", "/tmp/bundles",
    ])
    assert args.cmd == "recipegf-export"
    assert args.site == "punch"
    assert args.limit == 5
    assert args.dry_run is True
    assert args.out == "/tmp/bundles"
    assert args.reset is False


def test_export_reset_args():
    p = build_arg_parser()
    args = p.parse_args(["recipegf-export", "--reset", "--except-version", "v0", "--yes"])
    assert args.reset is True
    assert args.except_version == "v0"
    assert args.yes is True


def test_export_review_subcommand_registered():
    p = build_arg_parser()
    args = p.parse_args(["recipegf-export", "review-proposals", "--decided-by", "alice"])
    assert args.recipegf_cmd == "review-proposals"
    assert args.decided_by == "alice"


def test_run_export_review_returns_zero(capsys):
    # The pure eval runs with no DB — --review must not require TEST_DB_URL.
    p = build_arg_parser()
    args = p.parse_args(["recipegf-export", "--review"])
    rc = run_recipegf_export(args)
    out = capsys.readouterr().out.lower()
    assert "passed" in out
    assert rc == 0
