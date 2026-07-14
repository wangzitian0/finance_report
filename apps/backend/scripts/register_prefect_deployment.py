#!/usr/bin/env python3
"""Register (or update) the durable-parse Prefect deployment (EPIC-019).

Run once per worker container start, before ``prefect worker start`` — see
``scripts/prefect_worker_entrypoint.sh``. Idempotent: Prefect's ``.deploy()``
upserts by (flow name, deployment name), so re-running on every deploy just
updates the existing deployment's metadata rather than creating a duplicate.

Deploys from the LOCAL source already baked into this image (the worker runs
the same promoted backend image as the API, per the promote-not-rebuild
release model) — no Docker build/push step, since the work pool executes flow
runs as plain OS processes inside the worker container's own
filesystem/Python environment.

Uses a DEDICATED "finance-report" work pool, not the platform's "default"
pool: every environment's Prefect server also runs a shared generic worker
(``platform-prefect-worker*``) polling "default" for unrelated services, and
that worker's image has no finance_report app code. Registering onto
"default" makes our flow runs race the generic worker for pickup — when it
wins, the run crashes (``FileNotFoundError: /app``) and the statement is
orphaned in "parsing" forever (found via staging E2E gate failure on the
v0.1.38 deploy, 2026-07-14). The pool is created idempotently below since,
unlike "default", it does not pre-exist on a fresh environment.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

WORK_POOL_NAME = "finance-report"
DEPLOYMENT_NAME = "parse-statement"


async def _ensure_work_pool_exists(name: str) -> None:
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import WorkPoolCreate
    from prefect.exceptions import ObjectNotFound

    async with get_client() as client:
        try:
            await client.read_work_pool(name)
        except ObjectNotFound:
            await client.create_work_pool(WorkPoolCreate(name=name, type="process"))


def main() -> int:
    from src.extraction.extension.statement_flow import parse_statement_flow

    asyncio.run(_ensure_work_pool_exists(WORK_POOL_NAME))

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
