#!/usr/bin/env python
"""Apply branch protection rules across GitHub and Forgejo using one config file.

Usage:
  python scripts/apply_branch_protection.py --config scripts/branch_protection.targets.example.json
  python scripts/apply_branch_protection.py --config scripts/branch_protection.targets.example.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


@dataclass
class Target:
    provider: str
    owner: str
    repo: str
    branch: str
    token_env: str
    required_checks: List[str]
    required_approvals: int
    enforce_admins: bool
    require_conversation_resolution: bool
    forgejo_api_base: str


class BranchProtectionError(RuntimeError):
    """Raised when a branch protection API call fails."""


def _load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise BranchProtectionError("Config root must be a JSON object")
    return data


def _merge_target(defaults: Dict[str, Any], raw_target: Dict[str, Any]) -> Target:
    merged = dict(defaults)
    merged.update(raw_target)

    provider = str(merged.get("provider", "")).strip().lower()
    if provider not in {"github", "forgejo"}:
        raise BranchProtectionError(f"Unsupported provider: {provider}")

    required_checks_raw = merged.get("required_checks") or []
    if not isinstance(required_checks_raw, list):
        raise BranchProtectionError("required_checks must be an array")

    return Target(
        provider=provider,
        owner=str(merged.get("owner", "")).strip(),
        repo=str(merged.get("repo", "")).strip(),
        branch=str(merged.get("branch", "main")).strip(),
        token_env=str(merged.get("token_env", "")).strip(),
        required_checks=[str(item).strip() for item in required_checks_raw if str(item).strip()],
        required_approvals=int(merged.get("required_approvals", 1)),
        enforce_admins=bool(merged.get("enforce_admins", True)),
        require_conversation_resolution=bool(merged.get("require_conversation_resolution", True)),
        forgejo_api_base=str(merged.get("forgejo_api_base", "")).strip(),
    )


def _parse_targets(config: Dict[str, Any]) -> List[Target]:
    defaults = config.get("defaults") or {}
    raw_targets = config.get("targets") or []

    if not isinstance(defaults, dict):
        raise BranchProtectionError("defaults must be an object")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise BranchProtectionError("targets must be a non-empty array")

    parsed: List[Target] = []
    for index, item in enumerate(raw_targets, start=1):
        if not isinstance(item, dict):
            raise BranchProtectionError(f"targets[{index}] must be an object")
        target = _merge_target(defaults, item)
        if not target.owner or not target.repo:
            raise BranchProtectionError(f"targets[{index}] missing owner or repo")
        if not target.token_env:
            raise BranchProtectionError(f"targets[{index}] missing token_env")
        if target.provider == "forgejo" and not target.forgejo_api_base:
            raise BranchProtectionError(f"targets[{index}] missing forgejo_api_base")
        parsed.append(target)
    return parsed


def _github_payload(target: Target) -> Dict[str, Any]:
    required_status_checks: Optional[Dict[str, Any]] = None
    if target.required_checks:
        required_status_checks = {
            "strict": True,
            "contexts": target.required_checks,
        }

    return {
        "required_status_checks": required_status_checks,
        "enforce_admins": target.enforce_admins,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": max(0, target.required_approvals),
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "required_linear_history": False,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "required_conversation_resolution": target.require_conversation_resolution,
        "lock_branch": False,
        "allow_fork_syncing": False,
    }


def _forgejo_payload(target: Target) -> Dict[str, Any]:
    # Forgejo follows Gitea branch protection fields.
    return {
        "branch_name": target.branch,
        "enable_push": False,
        "enable_push_whitelist": False,
        "enable_merge_whitelist": False,
        "enable_status_check": bool(target.required_checks),
        "status_check_contexts": target.required_checks,
        "required_approvals": max(0, target.required_approvals),
        "block_on_official_review_requests": True,
        "block_on_outdated_branch": True,
        "block_on_rejected_reviews": True,
        "dismiss_stale_approvals": True,
    }


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _apply_github(target: Target, token: str, dry_run: bool) -> None:
    endpoint = f"https://api.github.com/repos/{target.owner}/{target.repo}/branches/{target.branch}/protection"
    payload = _github_payload(target)

    print(f"[github] {target.owner}/{target.repo}:{target.branch}")
    print(f"  endpoint: {endpoint}")
    print(f"  required_checks: {target.required_checks or ['<none>']}")
    print(f"  required_approvals: {target.required_approvals}")
    if dry_run:
        print("  mode: dry-run (no API call)")
        return

    response = requests.put(endpoint, headers=_headers(token), json=payload, timeout=60)
    if response.status_code // 100 != 2:
        raise BranchProtectionError(
            f"GitHub protection apply failed ({response.status_code}): {response.text}"
        )


def _apply_forgejo(target: Target, token: str, dry_run: bool) -> None:
    api_base = target.forgejo_api_base.rstrip("/")
    collection_endpoint = f"{api_base}/repos/{target.owner}/{target.repo}/branch_protections"
    single_endpoint = f"{collection_endpoint}/{target.branch}"
    payload = _forgejo_payload(target)

    print(f"[forgejo] {target.owner}/{target.repo}:{target.branch}")
    print(f"  endpoint: {collection_endpoint}")
    print(f"  required_checks: {target.required_checks or ['<none>']}")
    print(f"  required_approvals: {target.required_approvals}")
    if dry_run:
        print("  mode: dry-run (no API call)")
        return

    headers = _headers(token)
    create_response = requests.post(collection_endpoint, headers=headers, json=payload, timeout=60)

    if create_response.status_code // 100 == 2:
        return

    # Existing rule or provider differences: update by branch key.
    if create_response.status_code in {409, 422, 404, 405}:
        update_response = requests.put(single_endpoint, headers=headers, json=payload, timeout=60)
        if update_response.status_code // 100 == 2:
            return
        raise BranchProtectionError(
            "Forgejo protection update failed "
            f"({update_response.status_code}): {update_response.text}"
        )

    raise BranchProtectionError(
        f"Forgejo protection create failed ({create_response.status_code}): {create_response.text}"
    )


def _run_target(target: Target, dry_run: bool) -> None:
    token = os.getenv(target.token_env, "").strip()
    if not token and not dry_run:
        raise BranchProtectionError(
            f"Token environment variable not set: {target.token_env}"
        )

    if target.provider == "github":
        _apply_github(target, token=token, dry_run=dry_run)
        return

    if target.provider == "forgejo":
        _apply_forgejo(target, token=token, dry_run=dry_run)
        return

    raise BranchProtectionError(f"Unsupported provider: {target.provider}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply branch protection rules for GitHub and Forgejo targets"
    )
    parser.add_argument(
        "--config",
        default="scripts/branch_protection.targets.example.json",
        help="Path to branch protection target config JSON",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, script runs in dry-run mode.",
    )

    args = parser.parse_args(argv)
    dry_run = not args.apply

    try:
        config_path = Path(args.config)
        config = _load_config(config_path)
        targets = _parse_targets(config)

        print("=" * 72)
        print("Branch Protection Automation")
        print("=" * 72)
        print(f"Config: {config_path}")
        print(f"Mode: {'apply' if not dry_run else 'dry-run'}")
        print(f"Targets: {len(targets)}")
        print("")

        for target in targets:
            _run_target(target, dry_run=dry_run)
            print("")

        print("Completed successfully.")
        return 0
    except BranchProtectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: config file not found: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON config: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
