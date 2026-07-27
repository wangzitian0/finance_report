#!/usr/bin/env bash
# Health Check Script - thin delegate to the Python implementation.
#
# Ownership: this script's RESPONSIBILITY (post-deploy health probing) is
# infra's, not app's (#1535). The polling algorithm itself now lives in
# infra2_sdk.deploy_health (infra2-sdk v0.5.0); tools/health_check.py reuses
# it and layers Finance Report's own route-shadow diagnostics on top. This
# file only exists so tools/health_check.sh keeps the uniform
# tools/<name>.sh -> tools/_lib/shell/<name>.sh delegation shape every other
# shell command in tools/ follows (AC8.13.58) -- do not add logic here.
#
# Usage: unchanged -- see tools/health_check.sh / tools/health_check.py.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec python3 "$REPO_ROOT/tools/health_check.py" "$@"
