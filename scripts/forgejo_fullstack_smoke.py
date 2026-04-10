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
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from kinetic_devops import repo_context, repo_smoke_core


class ForgejoSmokeError(RuntimeError):
    """Raised when the Forgejo smoke flow fails."""


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
    return repo_context.normalize_forgejo_api_base(base_url, error_type=ForgejoSmokeError)


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
    repo_smoke_core.add_common_args(parser, token_env_default="FORGEJO_TOKEN")
    parser.set_defaults(owner=os.getenv("FORGEJO_OWNER", ""), owner_type=os.getenv("FORGEJO_OWNER_TYPE", "org"))
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    dry_run = not args.apply

    try:
        url_value = str(args.forgejo_url or "").strip()
        owner = str(args.owner or "").strip()
        host = ""

        if not url_value or not owner:
            detected = repo_context.detect_from_git(error_type=ForgejoSmokeError)
            if detected["provider"] != "forgejo":
                raise ForgejoSmokeError(
                    "Current git remote appears to be GitHub. Use github_fullstack_smoke.py or pass Forgejo URL/owner explicitly."
                )
            if not url_value:
                url_value = f"{detected.get('scheme', 'https')}://{detected['host']}/api/v1"
            if not owner:
                owner = detected["owner"]
            host = detected["host"]

        api_base = normalize_api_base(url_value)
        if not host:
            host = repo_context.host_from_url(api_base, error_type=ForgejoSmokeError)

        token, token_source = repo_smoke_core.resolve_token(
            provider="forgejo",
            env_name=args.token_env,
            token_service=args.token_service,
            token_account=args.token_account,
            host=host,
            owner=owner,
        )
        if not token and not dry_run:
            raise ForgejoSmokeError(f"Missing token. Checked {token_source}.")

        repo_name = str(args.repo or "").strip() or f"bp-smoke-{repo_smoke_core.random_suffix()}"

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
