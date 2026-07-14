#!/bin/bash
set -e

export PYTHONPATH=$PYTHONPATH:.

echo "🚀 Starting Prefect worker container entrypoint..."

# Wait for the vault-agent-rendered secrets file (mirrors the API entrypoint's
# CHECKPOINT-1 in scripts/entrypoint.sh) — this is a separate container, so it
# waits on the same shared /secrets volume independently.
echo "🔍 Waiting for Vault secrets to be rendered..."
while [ ! -f /secrets/.env ]; do
  echo "  ⏳ Secrets not ready yet, retrying..."
  sleep 1
done
echo "✅ Secrets file ready at /secrets/.env"

set -a
. /secrets/.env
set +a

# Idempotent: upserts the deployment by (flow name, deployment name) rather
# than duplicating it, so re-running on every container start/restart is safe.
python3 scripts/register_prefect_deployment.py

echo "🎬 Starting Prefect worker (pool: default)..."
exec prefect worker start --pool default
