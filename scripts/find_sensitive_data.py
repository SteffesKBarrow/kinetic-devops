import os
import re
import argparse
import sys
from typing import List, Tuple, Dict, Any

# Add the project root to the python path to allow importing the kinetic_devops
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from kinetic_devops.auth import KineticConfigManager

# Define generic patterns for sensitive information
GENERIC_PATTERNS = {
    "GENERIC_API_KEY": re.compile(r'["\']([a-zA-Z0-9_]{32,})["\']'),
    "GENERIC_TOKEN": re.compile(r'["\'](ey[a-zA-Z0-9_.-]+)["\']'),
}

# Directories to exclude from scanning
EXCLUDE_DIRS = {".git", ".vs", "venv", "__pycache__", "bin", "schemas", "templates", "reports"}

def get_sensitive_data_from_keyring() -> Dict[str, re.Pattern]:
    """
    Retrieves sensitive data from the keyring and creates regex patterns.
    """
    patterns = {}
    try:
        mgr = KineticConfigManager()
        configs = mgr.get_all_configs()
        for name, config in configs.items():
            if config.get("api_key"):
                patterns[f"API_KEY_FOR_{name}"] = re.compile(re.escape(config["api_key"]))
            if config.get("companies"):
                for company in config["companies"].split(','):
                    patterns[f"COMPANY_ID_{company.strip()}"] = re.compile(re.escape(company.strip()))
    except Exception as e:
        print(f"Could not get sensitive data from keyring: {e}")
    return patterns

def find_sensitive_data(
    start_path: str,
    custom_patterns: Dict[str, re.Pattern],
) -> List[Tuple[str, int, str, str]]:
    """
    Scans files in the given path for sensitive data based on defined patterns.

    Args:
        start_path (str): The starting directory to scan.
        custom_patterns (dict): A dictionary of regex patterns to search for.

    Returns:
        A list of tuples, where each tuple contains:
        (file_path, line_number, matched_pattern_name, matched_string)
    """
    findings = []
    all_patterns = {**GENERIC_PATTERNS, **custom_patterns}
    for root, dirs, files in os.walk(start_path):
        # Exclude specified directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith((".py", ".json", ".jsonc", ".xml", ".sql", ".bat", ".ps1", ".sh")):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            for pattern_name, regex in all_patterns.items():
                                for match in regex.finditer(line):
                                    findings.append(
                                        (file_path, i, pattern_name, match.group(0))
                                    )
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    return findings


def main():
    parser = argparse.ArgumentParser(
        description="Scan for sensitive data in the project."
    )
    parser.add_argument(
        "--path",
        default=".",
        help="The path to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--use-keyring",
        action="store_true",
        help="Use sensitive data from the keyring to find secrets.",
    )
    args = parser.parse_args()

    custom_patterns = {}
    if args.use_keyring:
        print("Getting sensitive data from keyring...")
        custom_patterns = get_sensitive_data_from_keyring()
        print(f"Found {len(custom_patterns)} sensitive data patterns from keyring.")

    findings = find_sensitive_data(args.path, custom_patterns)

    if findings:
        print("\nSensitive data found:")
        for file_path, line_num, pattern, match in findings:
            print(
                f"  - File: {file_path}, Line: {line_num}, Pattern: {pattern}, Match: {match}"
            )
            print("    Suggestion: Refactor to use the keyring for secure storage.")
    else:
        print("\nNo sensitive data found.")


if __name__ == "__main__":
    main()
