#!/bin/bash
set -e

export PYTHONPATH=$PYTHONPATH:.

echo "🚀 Starting Prefect worker container entrypoint..."

# Wait for the vault-agent-rendered secrets file (this container mirrors the
# same bounded-wait pattern infra2's compose.yaml uses inline for the
# `backend` service's own entrypoint override — this is a separate container
# on the same shared /secrets volume, so it waits independently). Bounded,
# not infinite: an unbounded wait would hang forever on a misconfigured or
# failed vault-agent instead of failing fast and letting the container
# restart/alert (review finding on PR #1854).
echo "🔍 Waiting for Vault secrets to be rendered..."
max_wait_seconds=60
waited=0
while [ ! -f /secrets/.env ]; do
  if [ "$waited" -ge "$max_wait_seconds" ]; then
    echo "❌ Secrets file /secrets/.env not rendered after ${max_wait_seconds}s — vault-agent may be misconfigured or down."
    exit 1
  fi
  echo "  ⏳ Secrets not ready yet, retrying... (${waited}/${max_wait_seconds}s)"
  sleep 1
  waited=$((waited + 1))
done
echo "✅ Secrets file ready at /secrets/.env"

set -a
. /secrets/.env
set +a

# Idempotent: upserts the deployment by (flow name, deployment name) rather
# than duplicating it, so re-running on every container start/restart is safe.
python3 scripts/register_prefect_deployment.py

echo "🎬 Starting Prefect worker (pool: finance-report)..."
# --type process: belt-and-suspenders auto-create if the pool is somehow
# missing (registration above already creates it) — non-interactive per
# Prefect's documented `worker start --pool <name> --type <type>` behavior.
exec prefect worker start --pool finance-report --type process
