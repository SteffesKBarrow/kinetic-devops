#!/usr/bin/env python
"""Unified full-stack smoke wrapper for GitHub and Forgejo.

Provider resolution order:
1. --provider (github|forgejo)
2. auto-detect from git remote.origin.url
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from kinetic_devops import repo_context

import github_fullstack_smoke
import forgejo_fullstack_smoke


class RepoSmokeError(RuntimeError):
    """Raised when unified smoke wrapper cannot resolve provider/context."""


def _detect_provider() -> str:
    detected = repo_context.detect_from_git(error_type=RepoSmokeError)
    return detected["provider"]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified GitHub/Forgejo full-stack smoke test")
    parser.add_argument("--provider", choices=("auto", "github", "forgejo"), default="auto")
    parser.add_argument("--owner", default="", help="Repository owner/user/org")
    parser.add_argument("--owner-type", choices=("org", "user"), default="org")
    parser.add_argument("--repo", default="", help="Repo name (default: generated temporary name)")
    parser.add_argument("--branch", default="main", help="Target branch")
    parser.add_argument("--required-check", default="Python Test Gate", help="Required status-check context")
    parser.add_argument("--required-approvals", type=int, default=1, help="Required PR approvals")
    parser.add_argument("--token-env", default="", help="Optional token env-var override")
    parser.add_argument("--token-service", default="kinetic-devops-tokens", help="Keyring service name")
    parser.add_argument("--token-account", default="", help="Keyring account override")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument("--keep-repo", action="store_true", help="Keep temporary repository")
    parser.add_argument("--apply", action="store_true", help="Execute API calls")
    parser.add_argument("--forgejo-url", default="", help="Forgejo base URL for forgejo provider")
    return parser.parse_args(argv)


def _build_common_args(args: argparse.Namespace, token_env_default: str) -> List[str]:
    out: List[str] = []
    if args.owner:
        out += ["--owner", args.owner]
    out += ["--owner-type", args.owner_type]
    if args.repo:
        out += ["--repo", args.repo]
    out += ["--branch", args.branch]
    out += ["--required-check", args.required_check]
    out += ["--required-approvals", str(args.required_approvals)]
    out += ["--token-env", args.token_env or token_env_default]
    out += ["--token-service", args.token_service]
    if args.token_account:
        out += ["--token-account", args.token_account]
    out += ["--timeout", str(args.timeout)]
    if args.keep_repo:
        out.append("--keep-repo")
    if args.apply:
        out.append("--apply")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        provider = args.provider
        if provider == "auto":
            provider = _detect_provider()

        if provider == "github":
            gh_args = _build_common_args(args, token_env_default="GITHUB_TOKEN")
            return github_fullstack_smoke.main(gh_args)

        if provider == "forgejo":
            fj_args = _build_common_args(args, token_env_default="FORGEJO_TOKEN")
            if args.forgejo_url:
                fj_args += ["--forgejo-url", args.forgejo_url]
            return forgejo_fullstack_smoke.main(fj_args)

        raise RepoSmokeError(f"Unsupported provider: {provider}")
    except RepoSmokeError as exc:
        print(f"SMOKE RESULT: FAIL - {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
