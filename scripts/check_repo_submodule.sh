#!/bin/bash
# Pre-commit hook to check if repo/ submodule points to latest infra2 main

set -e

echo "🔍 Checking repo/ submodule sync with infra2 main..."

cd repo

# Fetch latest main without creating noise
git fetch origin main --quiet 2>/dev/null || {
    echo "⚠️  Warning: Could not fetch repo/ submodule. Check network or authentication."
    exit 0  # Non-blocking, just warn
}

# Get commit SHAs
CURRENT_SHA=$(git rev-parse HEAD)
LATEST_SHA=$(git rev-parse origin/main)

if [ "$CURRENT_SHA" != "$LATEST_SHA" ]; then
    echo "❌ repo/ submodule is behind infra2 main!"
    echo ""
    echo "Current: $CURRENT_SHA"
    echo "Latest:  $LATEST_SHA"
    echo ""
    echo "To update:"
    echo "  cd repo && git checkout main && git pull && cd .. && git add repo"
    echo ""
    exit 1
fi

echo "✅ repo/ submodule is up-to-date with infra2 main"
exit 0
