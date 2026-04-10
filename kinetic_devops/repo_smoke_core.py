"""Shared utilities for provider smoke scripts."""

from __future__ import annotations

import argparse
import secrets
import string
from typing import Tuple

from kinetic_devops import repo_context

DEFAULT_TOKEN_SERVICE = "kinetic-devops-tokens"


def random_suffix(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def add_common_args(parser: argparse.ArgumentParser, *, token_env_default: str) -> None:
    parser.add_argument("--owner", default="", help="Repository owner/user/org")
    parser.add_argument(
        "--owner-type",
        choices=("org", "user"),
        default="org",
        help="Owner type for repository creation endpoint",
    )
    parser.add_argument("--repo", default="", help="Repo name (default: generated temporary name)")
    parser.add_argument("--branch", default="main", help="Target branch")
    parser.add_argument("--required-check", default="Python Test Gate", help="Required status-check context")
    parser.add_argument("--required-approvals", type=int, default=1, help="Required PR approvals")
    parser.add_argument("--token-env", default=token_env_default, help="Environment variable containing provider token")
    parser.add_argument(
        "--token-service",
        default=DEFAULT_TOKEN_SERVICE,
        help="Keyring service name used when env token is not set",
    )
    parser.add_argument(
        "--token-account",
        default="",
        help="Keyring account override used when env token is not set",
    )
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument("--keep-repo", action="store_true", help="Keep repository after successful run")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute API calls. Without this flag, script runs in dry-run mode.",
    )


def resolve_provider_owner(
    *,
    provider: str,
    owner: str,
    error_type: type[Exception],
) -> Tuple[str, str]:
    """Resolve owner and host for a provider, inferring from git remote when needed."""
    owner_value = str(owner or "").strip()

    if owner_value:
        return owner_value, ("github.com" if provider == "github" else "")

    detected = repo_context.detect_from_git(error_type=error_type)
    if detected["provider"] != provider:
        if provider == "github":
            raise error_type(
                "Current git remote does not appear to be GitHub. Use forgejo_fullstack_smoke.py or pass --owner explicitly."
            )
        raise error_type(
            "Current git remote appears to be GitHub. Use github_fullstack_smoke.py or pass Forgejo URL/owner explicitly."
        )

    return detected["owner"], detected["host"]


def resolve_token(
    *,
    provider: str,
    env_name: str,
    token_service: str,
    token_account: str,
    host: str,
    owner: str,
) -> Tuple[str, str]:
    token, source, _ = repo_context.resolve_token(
        env_name=str(env_name or "").strip(),
        token_service=str(token_service or DEFAULT_TOKEN_SERVICE).strip() or DEFAULT_TOKEN_SERVICE,
        token_account=str(token_account or "").strip(),
        host=str(host or "").strip().lower(),
        owner=str(owner or "").strip(),
        legacy_account=provider,
    )
    return token, source
