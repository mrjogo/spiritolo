import os

import pytest

from ingredients.cli import build_arg_parser


def test_arg_parser_review():
    p = build_arg_parser()
    args = p.parse_args(["--review"])
    assert args.review is True
    assert args.site is None
    assert args.limit is None
    assert args.dry_run is False
    assert args.reset is False


def test_arg_parser_full_worker_options():
    p = build_arg_parser()
    args = p.parse_args([
        "--site", "punch", "--limit", "100", "--dry-run",
    ])
    assert args.review is False
    assert args.site == "punch"
    assert args.limit == 100
    assert args.dry_run is True


def test_arg_parser_reset_flags():
    p = build_arg_parser()
    args = p.parse_args(["--reset", "--except-version", "v0", "--yes"])
    assert args.reset is True
    assert args.except_version == "v0"
    assert args.yes is True
