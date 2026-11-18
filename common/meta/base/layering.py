"""Five-layer package topology source of truth (``meta < infra < middleware < domain < app``)."""

from __future__ import annotations

from typing import Literal, get_args

PackageClass = Literal["meta", "infra", "middleware", "domain", "app"]

LAYER_RANK: dict[str, int] = {
    layer: rank for rank, layer in enumerate(get_args(PackageClass))
}

PACKAGE_LAYER: dict[str, PackageClass] = {
    "meta": "meta",
    "audit": "infra",
    "llm": "infra",
    "observability": "infra",
    "platform": "infra",
    "runtime": "infra",
    "testing": "infra",
    "counter": "middleware",
    "advisor": "domain",
    "extraction": "domain",
    "identity": "domain",
    "ledger": "domain",
    "portfolio": "domain",
    "pricing": "domain",
    "reconciliation": "domain",
    "reporting": "domain",
    "workflow": "domain",
    "backend": "app",
    "frontend": "app",
}
