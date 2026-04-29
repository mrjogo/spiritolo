"""Test the CLI dispatcher recognizes the new subcommands. End-to-end
behavior is exercised in the layer tests already; this is just shape."""

from ingredients.cli import build_arg_parser


def test_cli_recognizes_normalize_names_subcommand():
    args = build_arg_parser().parse_args(["normalize-names"])
    assert args.cmd == "normalize-names"


def test_cli_recognizes_normalize_names_resolve_pending():
    args = build_arg_parser().parse_args([
        "normalize-names", "resolve-pending", "--provider", "ollama",
    ])
    assert args.cmd == "normalize-names"
    assert args.normalize_cmd == "resolve-pending"
    assert args.provider == "ollama"


def test_cli_recognizes_cluster_subcommand():
    args = build_arg_parser().parse_args(["cluster"])
    assert args.cmd == "cluster"


def test_cli_recognizes_cluster_audit():
    args = build_arg_parser().parse_args(["cluster", "audit"])
    assert args.cmd == "cluster"
    assert args.cluster_cmd == "audit"


def test_cli_recognizes_promote_substances():
    args = build_arg_parser().parse_args(["promote-substances"])
    assert args.cmd == "promote-substances"


def test_cli_recognizes_dedup_all():
    args = build_arg_parser().parse_args(["dedup-all"])
    assert args.cmd == "dedup-all"


def test_cluster_reset_with_site_is_refused():
    """cluster --reset --site X is semantically broken; CLI rejects it with exit 2."""
    from unittest.mock import MagicMock, patch
    from ingredients.cli import run_cluster

    args = build_arg_parser().parse_args(["cluster", "--reset", "--site", "punch", "--yes"])
    # Patch IngredientsDatabase so no real DB connection is attempted.
    with patch("ingredients.cli.IngredientsDatabase") as mock_db_cls:
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        result = run_cluster(args)
    assert result == 2, f"Expected exit code 2, got {result}"
