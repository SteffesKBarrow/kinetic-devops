import sys
import argparse
from typing import Callable, Sequence
from .auth import main as auth_main
from .baq import main as baq_main
from .metafx import main as metafx_main
from .efx import main as efx_main
from .export_all import main as export_all_main
from .solutions import main as solutions_main
from .zdatatable import main as zdatatable_main
from .find_sensitive_data import main as find_sensitive_data_main
from .report_service import main as report_main
import importlib.metadata


TOOLS: dict[str, Callable[[], None]] = {
    "auth": auth_main,
    "baq": baq_main,
    "meta": metafx_main,
    "export": export_all_main,
    "solutions": solutions_main,
    "zdatatable": zdatatable_main,
    "find": find_sensitive_data_main,
    "efx": efx_main,
    "report": report_main,
}


def _build_parser(version: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kinetic SDK CLI Router")
    parser.add_argument("-v", "--version", action="version", version=f"Kinetic SDK v{version}")
    subparsers = parser.add_subparsers(dest="tool", help="Select the SDK tool to run")

    subparsers.add_parser("auth", help="Manage server configs and tokens")
    subparsers.add_parser("baq", help="Execute BAQ queries")
    subparsers.add_parser("meta", help="MetaFX tools (fetch UI metadata, core layer import/delete operations)")
    subparsers.add_parser("export", help="Export everything from an ExportAllTheThings EFx library")
    subparsers.add_parser("solutions", help="Backup and recreate Solution Workbench definitions")
    subparsers.add_parser("zdatatable", help="Detect/sync UD column drift from ZDataTable XML")
    subparsers.add_parser("find", help="Find sensitive data in the project")
    subparsers.add_parser("efx", help="Execute Epicor Functions")
    subparsers.add_parser("report", help="Upload and Extract Reports")
    return parser


def _dispatch_tool(tool_name: str, tool_args: Sequence[str]) -> None:
    old_argv = sys.argv
    try:
        # Delegate directly to the submodule entrypoint to avoid runpy RuntimeWarning behavior.
        sys.argv = [f"{old_argv[0]} {tool_name}", *tool_args]
        TOOLS[tool_name]()
    finally:
        sys.argv = old_argv


def main(argv: Sequence[str] | None = None) -> int:
    try:
        __version__ = importlib.metadata.version("kinetic-devops")
    except importlib.metadata.PackageNotFoundError:
        __version__ = "alpha-dev"

    args = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser(__version__)

    if not args:
        parser.print_help()
        return 1

    if args[0] in TOOLS:
        _dispatch_tool(args[0], args[1:])
        return 0

    # This handles router-level arguments like --version/--help and unknown command errors.
    parser.parse_args(args)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())