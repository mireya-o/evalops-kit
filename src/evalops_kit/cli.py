"""CLI entrypoints for EvalOps Kit."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from evalops_kit.errors import EvalOpsError


def _handle_run(args: argparse.Namespace) -> int:
    from evalops_kit.run import run_suite

    run_suite(suite_path=Path(args.suite), out_dir=Path(args.out))
    return 0


def _handle_diff(_args: argparse.Namespace) -> int:
    from evalops_kit.diff import build_diff_report, write_diff_report

    suite_path = None if _args.suite is None else Path(_args.suite)
    result = build_diff_report(
        base_path=Path(_args.base),
        cand_path=Path(_args.cand),
        suite_path=suite_path,
    )
    if _args.out is not None:
        write_diff_report(result.report_markdown, Path(_args.out))
    else:
        print(result.report_markdown, end="")
    return 2 if result.has_gate_failures else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalops-kit",
        description="EvalOps Kit command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    run_parser = subparsers.add_parser("run", help="Run evaluation workflows.")
    run_parser.add_argument("--suite", required=True, help="Path to suite TOML file.")
    run_parser.add_argument("--out", required=True, help="Output directory for run artifacts.")
    run_parser.set_defaults(handler=_handle_run)

    diff_parser = subparsers.add_parser("diff", help="Show differences between evaluation runs.")
    diff_parser.add_argument("--base", required=True, help="Run directory or summary.json path.")
    diff_parser.add_argument("--cand", required=True, help="Run directory or summary.json path.")
    diff_parser.add_argument("--suite", help="Optional suite TOML path for regression gates.")
    diff_parser.add_argument("--out", help="Optional output markdown file path.")
    diff_parser.set_defaults(handler=_handle_diff)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        handler = getattr(args, "handler", None)
        if handler is None:
            parser.error("No command selected.")
        return int(handler(args))
    except EvalOpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
