"""``common.audit`` — single-source bridge to ``apps/backend/src/audit`` (#2752)."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

_COMMON_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _COMMON_DIR.parents[1] / "apps" / "backend"
if str(_BACKEND_DIR) not in sys.path:
    # Append, never prepend: apps/backend/tests must not shadow the repo-root tests package.
    sys.path.append(str(_BACKEND_DIR))

_COMMON_ONLY = frozenset(
    {
        "contract",
        "extension.cascade_ownership",
        "money.guard",
        "money.conformance",
        "quantity.conformance",
        "ratio.conformance",
        "unit_price.conformance",
    }
)


class _AuditBridgeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith("common.audit."):
            return None
        rel = fullname[len("common.audit.") :]
        if rel in _COMMON_ONLY or any(rel.startswith(f"{m}.") for m in _COMMON_ONLY):
            return None
        backend_spec = importlib.util.find_spec(f"src.audit.{rel}")
        if backend_spec is None:
            return None
        return importlib.machinery.ModuleSpec(
            fullname,
            self,
            is_package=backend_spec.submodule_search_locations is not None,
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        fullname = module.__name__
        rel = fullname[len("common.audit.") :]
        backend_mod = importlib.import_module(f"src.audit.{rel}")
        if hasattr(backend_mod, "__path__"):
            common_sub = str(_COMMON_DIR / rel.replace(".", "/"))
            if common_sub not in backend_mod.__path__ and Path(common_sub).is_dir():
                backend_mod.__path__.append(common_sub)
        sys.modules[fullname] = backend_mod
        parent_name, _, attr = fullname.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, attr, backend_mod)


if not any(type(f).__name__ == "_AuditBridgeFinder" for f in sys.meta_path):
    sys.meta_path.insert(0, _AuditBridgeFinder())

import src.audit as _src_audit  # noqa: E402
from src.audit import *  # noqa: E402,F401,F403

if TYPE_CHECKING:
    from common.audit.contract import CONTRACT as CONTRACT

__all__ = ["CONTRACT", *_src_audit.__all__]


def __getattr__(name: str):
    if name == "CONTRACT":
        from common.audit.contract import CONTRACT

        return CONTRACT
    return getattr(_src_audit, name)
