#!/usr/bin/env python3
"""Command wrapper for the one AC-index consistency gate."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.extraction.source_capability import SOURCE_CAPABILITIES  # noqa: E402
from common.testing.ac_graph import AcGraph  # noqa: E402
from common.testing.check_ac_index import run_ac_index  # noqa: E402
from common.testing.source_capability_proof import (  # noqa: E402
    validate_source_capability_proofs,
)


def _source_capability_proof_errors(_repo_root: Path, graph: AcGraph) -> list[str]:
    return validate_source_capability_proofs(SOURCE_CAPABILITIES, graph.proofs)


def main(argv: Sequence[str] | None = None) -> int:
    return run_ac_index(
        argv,
        repo_integrity_checks=(_source_capability_proof_errors,),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
