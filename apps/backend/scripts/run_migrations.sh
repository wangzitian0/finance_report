#!/bin/bash
# Run database migrations before starting the application

set -e

echo "Running database migrations..."
alembic upgrade head
echo "Migrations completed successfully"
