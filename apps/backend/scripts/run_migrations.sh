#!/bin/bash
# Run database migrations before starting the application
# Note: Execute permissions are set in Dockerfile when copying this script

set -e

echo "Running database migrations..."
alembic upgrade head
echo "Migrations completed successfully"
