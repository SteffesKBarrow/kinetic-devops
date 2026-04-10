#!/usr/bin/env python
"""API smoke test for GitHub branch-protection flow on a fresh repository.

This script can run against a temporary repository in GitHub to validate:
1. Repository creation
2. Branch protection apply
3. Branch protection verification
4. Optional repository cleanup

Use dry-run mode by default to preview actions without API calls.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from kinetic_devops import repo_context, repo_smoke_core


class GitHubSmokeError(RuntimeError):
    """Raised when the GitHub smoke flow fails."""


@dataclass
class SmokeConfig:
    owner: str
    owner_type: str
    repo_name: str
    branch: str
    required_check: str
    required_approvals: int
    token: str
    keep_repo: bool
    timeout: int


def build_branch_protection_payload(required_check: str, required_approvals: int) -> Dict[str, Any]:
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": [required_check],
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": max(0, int(required_approvals)),
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "required_linear_history": False,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "required_conversation_resolution": True,
        "lock_branch": False,
        "allow_fork_syncing": False,
    }


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def create_repo(session: requests.Session, cfg: SmokeConfig) -> None:
    payload = {
        "name": cfg.repo_name,
        "description": "Temporary branch protection smoke-test repository",
        "private": True,
        "auto_init": True,
    }

    if cfg.owner_type == "org":
        endpoint = f"https://api.github.com/orgs/{cfg.owner}/repos"
    else:
        endpoint = "https://api.github.com/user/repos"

    response = session.post(endpoint, json=payload, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise GitHubSmokeError(f"Repo creation failed ({response.status_code}): {response.text}")


def apply_branch_protection(session: requests.Session, cfg: SmokeConfig) -> None:
    payload = build_branch_protection_payload(cfg.required_check, cfg.required_approvals)
    endpoint = f"https://api.github.com/repos/{cfg.owner}/{cfg.repo_name}/branches/{cfg.branch}/protection"

    response = session.put(endpoint, json=payload, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise GitHubSmokeError(
            f"Branch protection apply failed ({response.status_code}): {response.text}"
        )


def verify_branch_protection(session: requests.Session, cfg: SmokeConfig) -> None:
    endpoint = f"https://api.github.com/repos/{cfg.owner}/{cfg.repo_name}/branches/{cfg.branch}/protection"
    response = session.get(endpoint, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise GitHubSmokeError(f"Branch protection fetch failed ({response.status_code}): {response.text}")

    body = response.json()
    checks = (body.get("required_status_checks") or {}).get("contexts") or []
    approvals = int(
        ((body.get("required_pull_request_reviews") or {}).get("required_approving_review_count") or 0)
    )

    if cfg.required_check not in checks:
        raise GitHubSmokeError(
            f"Expected required check '{cfg.required_check}' not found in {checks}"
        )

    if approvals != max(0, cfg.required_approvals):
        raise GitHubSmokeError(
            f"Expected required approvals {cfg.required_approvals}, got {approvals}"
        )


def delete_repo(session: requests.Session, cfg: SmokeConfig) -> None:
    endpoint = f"https://api.github.com/repos/{cfg.owner}/{cfg.repo_name}"
    response = session.delete(endpoint, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise GitHubSmokeError(f"Repo delete failed ({response.status_code}): {response.text}")


def run_smoke(cfg: SmokeConfig, dry_run: bool) -> None:
    print("=" * 72)
    print("GitHub Full-Stack Smoke")
    print("=" * 72)
    print(f"Owner: {cfg.owner} ({cfg.owner_type})")
    print(f"Repo: {cfg.repo_name}")
    print(f"Branch: {cfg.branch}")
    print(f"Required check: {cfg.required_check}")
    print(f"Required approvals: {cfg.required_approvals}")
    print(f"Cleanup: {'delete repo after test' if not cfg.keep_repo else 'keep repo'}")

    if dry_run:
        print("Mode: dry-run (no API calls)")
        print("Steps:")
        print("1. Create repository")
        print("2. Apply branch protection")
        print("3. Verify branch protection")
        print("4. Delete repository (unless --keep-repo)")
        return

    session = requests.Session()
    session.headers.update(_headers(cfg.token))

    created = False
    try:
        create_repo(session, cfg)
        created = True
        print("[ok] repository created")

        apply_branch_protection(session, cfg)
        print("[ok] branch protection applied")

        verify_branch_protection(session, cfg)
        print("[ok] branch protection verified")
    finally:
        if created and not cfg.keep_repo:
            try:
                delete_repo(session, cfg)
                print("[ok] repository deleted")
            except Exception as exc:  # pragma: no cover
                print(f"[warn] cleanup failed: {exc}", file=sys.stderr)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GitHub branch-protection full-stack smoke test")
    repo_smoke_core.add_common_args(parser, token_env_default="GITHUB_TOKEN")
    parser.set_defaults(owner=os.getenv("GITHUB_OWNER", ""), owner_type=os.getenv("GITHUB_OWNER_TYPE", "org"))
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    dry_run = not args.apply

    try:
        owner, detected_host = repo_smoke_core.resolve_provider_owner(
            provider="github",
            owner=args.owner,
            error_type=GitHubSmokeError,
        )
        if not detected_host:
            detected_host = "github.com"

        token, token_source = repo_smoke_core.resolve_token(
            provider="github",
            env_name=args.token_env,
            token_service=args.token_service,
            token_account=args.token_account,
            host=detected_host,
            owner=owner,
        )
        if not token and not dry_run:
            raise GitHubSmokeError(f"Missing token. Checked {token_source}.")

        repo_name = str(args.repo or "").strip() or f"bp-smoke-{repo_smoke_core.random_suffix()}"

        cfg = SmokeConfig(
            owner=owner,
            owner_type=args.owner_type,
            repo_name=repo_name,
            branch=args.branch,
            required_check=args.required_check,
            required_approvals=args.required_approvals,
            token=token,
            keep_repo=bool(args.keep_repo),
            timeout=max(1, int(args.timeout)),
        )

        run_smoke(cfg, dry_run=dry_run)
        print("SMOKE RESULT: PASS")
        return 0
    except GitHubSmokeError as exc:
        print(f"SMOKE RESULT: FAIL - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
