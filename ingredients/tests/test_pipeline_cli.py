"""Pipeline CLI: argument parsing + dispatch to stages / cold-build (no DB)."""

from __future__ import annotations

import pytest

from ingredients import cli
from ingredients.pipeline.stages import STAGE_ORDER


def test_parser_accepts_every_stage_and_cold_build():
    parser = cli.build_parser()
    for cmd in [*STAGE_ORDER, "cold-build"]:
        args = parser.parse_args([cmd, "--site", "punch", "--limit", "5"])
        assert args.cmd == cmd
        assert args.site == "punch" and args.limit == 5


def test_run_dispatches_to_the_named_stage(monkeypatch):
    seen = {}

    def fake_parse(job, conn, providers):
        seen["job"] = job
        return {"parsed": 3}

    monkeypatch.setitem(cli.STAGE_FNS, "parse", fake_parse)
    args = cli.build_parser().parse_args(["parse", "--site", "imbibe", "--limit", "2"])
    result = cli.run(args, conn=object())
    assert result == {"parse": {"parsed": 3}}
    assert seen["job"]["payload"] == {"site": "imbibe", "limit": 2}


def test_cold_build_runs_every_stage_in_order(monkeypatch):
    calls = []

    def make(stage):
        def fn(job, conn, providers):
            calls.append(stage)
            return {}
        return fn

    for stage in STAGE_ORDER:
        monkeypatch.setitem(cli.STAGE_FNS, stage, make(stage))
    args = cli.build_parser().parse_args(["cold-build"])
    cli.run(args, conn=object())
    assert calls == STAGE_ORDER


def test_missing_command_errors():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])
