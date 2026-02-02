#!/usr/bin/env bash
# scripts/install_git_hooks.sh
#
# Install recommended git hooks for automatic resource cleanup

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

echo "🔧 Installing git hooks..."

cat > "$HOOKS_DIR/post-push" << 'EOF'
#!/usr/bin/env bash
# .git/hooks/post-push
#
# Automatically clean up orphaned test databases after git push
# This hook only removes resources that are safe to delete:
# - Test databases from interrupted test runs
# - Does NOT touch development data or running tests

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo ""
echo "🧹 Post-push cleanup: Checking for orphaned test databases..."

if ! command -v python3 &> /dev/null; then
    echo "   ⚠️  Python3 not found, skipping cleanup"
    exit 0
fi

cd "$REPO_ROOT"

python3 scripts/cleanup_orphaned_dbs.py 2>&1 | sed 's/^/   /'

echo ""
EOF

chmod +x "$HOOKS_DIR/post-push"

echo "✅ Installed: post-push hook (automatic cleanup of orphaned test databases)"
echo ""
echo "To disable the hook, run:"
echo "  rm .git/hooks/post-push"
