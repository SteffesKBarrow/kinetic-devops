#!/usr/bin/env python
"""API smoke test for Forgejo branch-protection flow on a fresh repository.

This script can run against a local/virtual Forgejo instance or a remote host.

Flow in apply mode:
1. Create a repository
2. Apply branch protection on main
3. Fetch and validate branch protection
4. Optionally delete the repository

Use dry-run mode by default to preview actions without API calls.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


class ForgejoSmokeError(RuntimeError):
    """Raised when the Forgejo smoke flow fails."""


DEFAULT_TOKEN_SERVICE = "kinetic-devops-tokens"


@dataclass
class SmokeConfig:
    api_base: str
    owner: str
    owner_type: str
    repo_name: str
    branch: str
    required_check: str
    required_approvals: int
    token: str
    keep_repo: bool
    timeout: int


def normalize_api_base(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ForgejoSmokeError("Forgejo URL is required")
    if value.endswith("/api/v1"):
        return value
    return f"{value}/api/v1"


def build_branch_protection_payload(branch: str, required_check: str, required_approvals: int) -> Dict[str, Any]:
    return {
        "branch_name": branch,
        "enable_push": False,
        "enable_push_whitelist": False,
        "enable_merge_whitelist": False,
        "enable_status_check": True,
        "status_check_contexts": [required_check],
        "required_approvals": max(0, int(required_approvals)),
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


def _random_suffix(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _resolve_token(token_env: str, token_service: str, token_account: str) -> tuple[str, str]:
    """Resolve token from env var first, then keyring fallback."""
    env_name = str(token_env or "").strip()
    token = str(os.getenv(env_name, "") or "").strip()
    if token:
        return token, f"env:{env_name}"

    service = str(token_service or DEFAULT_TOKEN_SERVICE).strip() or DEFAULT_TOKEN_SERVICE
    account = str(token_account or "forgejo").strip() or "forgejo"

    try:
        import keyring

        token = str(keyring.get_password(service, account) or "").strip()
    except Exception:
        token = ""

    if token:
        return token, f"keyring:{service}/{account}"

    return "", f"env:{env_name} or keyring:{service}/{account}"


def create_repo(session: requests.Session, cfg: SmokeConfig) -> None:
    payload = {
        "name": cfg.repo_name,
        "description": "Temporary branch protection smoke-test repository",
        "private": True,
        "auto_init": True,
        "default_branch": cfg.branch,
    }

    if cfg.owner_type == "org":
        endpoint = f"{cfg.api_base}/orgs/{cfg.owner}/repos"
    else:
        endpoint = f"{cfg.api_base}/user/repos"

    response = session.post(endpoint, json=payload, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise ForgejoSmokeError(f"Repo creation failed ({response.status_code}): {response.text}")


def apply_branch_protection(session: requests.Session, cfg: SmokeConfig) -> None:
    payload = build_branch_protection_payload(cfg.branch, cfg.required_check, cfg.required_approvals)
    collection = f"{cfg.api_base}/repos/{cfg.owner}/{cfg.repo_name}/branch_protections"
    single = f"{collection}/{cfg.branch}"

    response = session.post(collection, json=payload, timeout=cfg.timeout)
    if response.status_code // 100 == 2:
        return

    if response.status_code in {404, 405, 409, 422}:
        update = session.put(single, json=payload, timeout=cfg.timeout)
        if update.status_code // 100 == 2:
            return
        raise ForgejoSmokeError(
            f"Branch protection update failed ({update.status_code}): {update.text}"
        )

    raise ForgejoSmokeError(
        f"Branch protection create failed ({response.status_code}): {response.text}"
    )


def verify_branch_protection(session: requests.Session, cfg: SmokeConfig) -> None:
    endpoint = f"{cfg.api_base}/repos/{cfg.owner}/{cfg.repo_name}/branch_protections/{cfg.branch}"
    response = session.get(endpoint, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise ForgejoSmokeError(f"Branch protection fetch failed ({response.status_code}): {response.text}")

    body = response.json()
    contexts = body.get("status_check_contexts") or []
    approvals = int(body.get("required_approvals", 0))

    if cfg.required_check not in contexts:
        raise ForgejoSmokeError(
            f"Expected required check '{cfg.required_check}' not found in {contexts}"
        )

    if approvals != max(0, cfg.required_approvals):
        raise ForgejoSmokeError(
            f"Expected required approvals {cfg.required_approvals}, got {approvals}"
        )


def delete_repo(session: requests.Session, cfg: SmokeConfig) -> None:
    endpoint = f"{cfg.api_base}/repos/{cfg.owner}/{cfg.repo_name}"
    response = session.delete(endpoint, timeout=cfg.timeout)
    if response.status_code // 100 != 2:
        raise ForgejoSmokeError(f"Repo delete failed ({response.status_code}): {response.text}")


def run_smoke(cfg: SmokeConfig, dry_run: bool) -> None:
    print("=" * 72)
    print("Forgejo Full-Stack Smoke")
    print("=" * 72)
    print(f"API base: {cfg.api_base}")
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
    parser = argparse.ArgumentParser(description="Run Forgejo branch-protection full-stack smoke test")
    parser.add_argument("--forgejo-url", default=os.getenv("FORGEJO_URL", ""), help="Forgejo base URL")
    parser.add_argument("--owner", default=os.getenv("FORGEJO_OWNER", ""), help="Repository owner/user/org")
    parser.add_argument(
        "--owner-type",
        choices=("org", "user"),
        default=os.getenv("FORGEJO_OWNER_TYPE", "org"),
        help="Owner type for repository creation endpoint",
    )
    parser.add_argument("--repo", default="", help="Repo name (default: generated temporary name)")
    parser.add_argument("--branch", default="main", help="Target branch")
    parser.add_argument("--required-check", default="Python Test Gate", help="Required status-check context")
    parser.add_argument("--required-approvals", type=int, default=1, help="Required PR approvals")
    parser.add_argument("--token-env", default="FORGEJO_TOKEN", help="Environment variable containing Forgejo token")
    parser.add_argument(
        "--token-service",
        default=DEFAULT_TOKEN_SERVICE,
        help="Keyring service name used when env token is not set",
    )
    parser.add_argument(
        "--token-account",
        default="forgejo",
        help="Keyring account name used when env token is not set",
    )
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument("--keep-repo", action="store_true", help="Keep repository after successful run")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute API calls. Without this flag, script runs in dry-run mode.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    dry_run = not args.apply

    try:
        api_base = normalize_api_base(args.forgejo_url)
        owner = str(args.owner or "").strip()
        if not owner:
            raise ForgejoSmokeError("Owner is required. Set --owner or FORGEJO_OWNER.")

        token, token_source = _resolve_token(args.token_env, args.token_service, args.token_account)
        if not token and not dry_run:
            raise ForgejoSmokeError(f"Missing token. Checked {token_source}.")

        repo_name = str(args.repo or "").strip() or f"bp-smoke-{_random_suffix()}"

        cfg = SmokeConfig(
            api_base=api_base,
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
    except ForgejoSmokeError as exc:
        print(f"SMOKE RESULT: FAIL - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
