#!/usr/bin/env python3
"""Register (or update) the durable-parse Prefect deployment (EPIC-019).

Run once per worker container start, before ``prefect worker start`` — see
``scripts/prefect_worker_entrypoint.sh``. Idempotent: Prefect's ``.deploy()``
upserts by (flow name, deployment name), so re-running on every deploy just
updates the existing deployment's metadata rather than creating a duplicate.

Deploys from the LOCAL source already baked into this image (the worker runs
the same promoted backend image as the API, per the promote-not-rebuild
release model), targeting the process-type "default" work pool — no Docker
build/push step, since the work pool executes flow runs as plain OS processes
inside the worker container's own filesystem/Python environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

WORK_POOL_NAME = "default"
DEPLOYMENT_NAME = "parse-statement"


def main() -> int:
    from src.extraction.extension.statement_flow import parse_statement_flow

    parse_statement_flow.from_source(
        source=str(BACKEND_ROOT),
        entrypoint="src/extraction/extension/statement_flow.py:parse_statement_flow",
    ).deploy(
        name=DEPLOYMENT_NAME,
        work_pool_name=WORK_POOL_NAME,
    )
    print(f"Registered deployment '{DEPLOYMENT_NAME}' on work pool '{WORK_POOL_NAME}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
