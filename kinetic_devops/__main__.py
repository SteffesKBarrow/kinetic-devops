import sys
import argparse
from .auth import main as auth_main
from .baq import main as baq_main
from .metafx import main as metafx_main
from .efx import main as efx_main
from .find_sensitive_data import main as find_sensitive_data_main
from .report_service import main as report_main

def main():
    parser = argparse.ArgumentParser(description="Kinetic SDK CLI Router")
    subparsers = parser.add_subparsers(dest="tool", help="Select the SDK tool to run")

    # Mapping sub-commands to the main functions of your modules
    subparsers.add_parser("auth", help="Manage server configs and tokens")
    subparsers.add_parser("baq", help="Execute BAQ queries")
    subparsers.add_parser("meta", help="Fetch UI metadata")
    subparsers.add_parser("find", help="Find sensitive data in the project")
    subparsers.add_parser("efx", help="Execute Epicor Functions")
    subparsers.add_parser("report", help="Upload and Extract Reports")

    # If no arguments, print help
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    # Parse only the first argument to determine which tool to use
    args, remaining_args = parser.parse_known_args()

    # Rewrite sys.argv so the sub-module's argparse works correctly
    sys.argv = [sys.argv[0]] + remaining_args

    if args.tool == "auth":
        auth_main()
    elif args.tool == "baq":
        baq_main()
    elif args.tool == "meta":
        metafx_main()
    elif args.tool == "find":
        find_sensitive_data_main()
    elif args.tool == "efx":
        efx_main()
    elif args.tool == "report":
        report_main()

if __name__ == "__main__":
    main()