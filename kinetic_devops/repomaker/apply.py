"""RepoMaker apply entrypoint.

This module exposes the existing config-driven branch protection automation
under the RepoMaker package namespace without changing script compatibility.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import List, Optional


_MODULE_CACHE: ModuleType | None = None


def _load_apply_script_module() -> ModuleType:
    global _MODULE_CACHE
    if _MODULE_CACHE is not None:
        return _MODULE_CACHE

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "apply_branch_protection.py"
    spec = importlib.util.spec_from_file_location("_repomaker_apply_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/apply_branch_protection.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE = module
    return module


def main(argv: Optional[List[str]] = None) -> int:
    module = _load_apply_script_module()
    return module.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
