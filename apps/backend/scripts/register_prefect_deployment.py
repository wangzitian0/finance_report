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
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]

WORK_POOL_NAME = "finance-report"
DEPLOYMENT_NAME = "parse-statement"


async def _ensure_work_pool_exists(name: str) -> None:
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import WorkPoolCreate
    from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound

    async with get_client() as client:
        try:
            await client.read_work_pool(name)
        except ObjectNotFound:
            try:
                await client.create_work_pool(WorkPoolCreate(name=name, type="process"))
            except ObjectAlreadyExists:
                # A concurrent worker start (e.g. old+new containers briefly
                # overlapping during a rolling restart) can also observe
                # ObjectNotFound and win the create race first — the pool
                # existing either way is the desired end state (review finding
                # on PR #1857).
                pass


def main() -> int:
    import os

    from src.config import settings
    from src.statement_flow import (
        classify_statement_flow,
        market_data_sync_flow,
        parse_statement_flow,
        parsing_supervisor_reap_flow,
        staging_db_hygiene_flow,
        storage_sweep_flow,
    )

    asyncio.run(_ensure_work_pool_exists(WORK_POOL_NAME))

    deployments: list[tuple[Any, str, str, dict[str, Any]]] = [
        (parse_statement_flow, DEPLOYMENT_NAME, "src/statement_flow.py:parse_statement_flow", {}),
        (classify_statement_flow, "classify-statement", "src/statement_flow.py:classify_statement_flow", {}),
        # Daily 22:00 SGT = 14:00 UTC
        (
            market_data_sync_flow,
            "market-data-sync",
            "src/statement_flow.py:market_data_sync_flow",
            {"cron": "0 14 * * *"},
        ),
        (storage_sweep_flow, "storage-sweep", "src/statement_flow.py:storage_sweep_flow", {"cron": "0 3 * * *"}),
        (
            parsing_supervisor_reap_flow,
            "parsing-supervisor-reap",
            "src/statement_flow.py:parsing_supervisor_reap_flow",
            {"interval": 60},
        ),
    ]
    env_name = (os.environ.get("ENVIRONMENT") or settings.environment or "").strip().lower()
    if env_name == "staging":
        deployments.append(
            (
                staging_db_hygiene_flow,
                "staging-db-hygiene",
                "src/statement_flow.py:staging_db_hygiene_flow",
                {"cron": "47 3 * * *"},
            )
        )

    for flow_obj, name, entrypoint, schedule_kw in deployments:
        flow_obj.from_source(source=str(BACKEND_ROOT), entrypoint=entrypoint).deploy(
            name=name,
            work_pool_name=WORK_POOL_NAME,
            **schedule_kw,
        )
        print(f"Registered deployment '{name}' on work pool '{WORK_POOL_NAME}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
