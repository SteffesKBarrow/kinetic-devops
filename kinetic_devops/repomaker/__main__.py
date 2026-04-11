"""RepoMaker modular CLI entrypoint.

Usage:
  python -m kinetic_devops.repomaker apply [args...]
  python -m kinetic_devops.repomaker reposmith [args...]
  python -m kinetic_devops.repomaker smoke [args...]
"""

from __future__ import annotations

import sys
from typing import List, Optional

from kinetic_devops.repomaker import apply
from kinetic_devops.repomaker import reposmith


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help"}:
        print("RepoMaker modular CLI")
        print("Usage:")
        print("  repomaker apply [args...]")
        print("  repomaker reposmith [args...]")
        print("  repomaker smoke [args...]")
        return 0

    command = str(args[0]).strip().lower()
    remainder: List[str] = args[1:]

    if command == "apply":
        return apply.main(remainder)

    if command in {"reposmith", "smoke"}:
        return reposmith.main(remainder)

    print(f"Unknown RepoMaker command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
