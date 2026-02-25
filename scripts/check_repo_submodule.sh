#!/bin/bash
# Pre-commit hook to check if repo/ submodule points to latest infra2 main
set -e

echo "🔍 Checking repo/ submodule sync with infra2 main..."

# Resolve repository root to avoid depending on the current working directory
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "⚠️  Warning: Could not determine Git repository root. Skipping repo/ submodule check."
    exit 0
}

cd "$REPO_ROOT" || {
    echo "⚠️  Warning: Could not change to repository root directory '$REPO_ROOT'. Skipping repo/ submodule check."
    exit 0
}

if [ ! -d "repo/.git" ]; then
    echo "❌ repo/ submodule is not initialized."
    echo ""
    echo "To initialize the submodule, run:"
    echo "  git submodule update --init --recursive"
    echo ""
    exit 1
fi

cd repo || {
    echo "⚠️  Warning: Could not cd into repo/ submodule directory. Skipping check."
    exit 0
}
# Fetch latest main without creating noise
git fetch origin main --quiet 2>/dev/null || {
    echo "⚠️  Warning: Could not fetch repo/ submodule. Check network or authentication."
    exit 0  # Non-blocking, just warn
}
# Get commit SHAs
CURRENT_SHA=$(git rev-parse HEAD)
LATEST_SHA=$(git rev-parse origin/main)
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