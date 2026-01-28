#!/usr/bin/env bash
# scripts/infra.sh
# 
# Starts the infrastructure containers using either docker or podman.
# Priority: docker > podman

set -e

# Detect runtime
if command -v docker >/dev/null 2>&1; then
    RUNTIME="docker"
elif command -v podman >/dev/null 2>&1; then
    RUNTIME="podman"
else
    echo "❌ Error: Neither 'docker' nor 'podman' found."
    echo "   Please install a container runtime to proceed."
    exit 1
fi

echo "🐳 Found runtime: $RUNTIME"
echo "🐘 Starting Infrastructure (Postgres, Redis, MinIO)..."
echo "   (Press Ctrl+C to stop)"

# Execute compose command
# Note: We use 'exec' so this script process is replaced by the runtime process,
# ensuring signals like Ctrl+C are passed directly to docker/podman.
# We explicitly enable the 'infra' profile to start DB/Redis/MinIO.
exec $RUNTIME compose -f docker-compose.yml --profile infra up postgres redis minio minio-init
