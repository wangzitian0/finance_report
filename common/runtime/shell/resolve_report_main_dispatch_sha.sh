#!/usr/bin/env bash
# Decide which SHA (if any) notify-infra2.yml should dispatch to infra2's
# report-branch-main deploy.
#
# #1534 (AC8.13.146): split out of the workflow's inline bash conditional so
# the decision is real-execution testable (tests/tooling/test_report_main_dispatch.py
# invokes this script via subprocess with controlled inputs), not verified by
# matching literal bash-line substrings against the workflow YAML's source text.
#
# Usage: resolve_report_main_dispatch_sha.sh <event_name> <workflow_run_sha> <latest_main_sha>
#
# Behavior:
#   event_name != "workflow_run"   -> print latest_main_sha, exit 0 (manual
#                                      workflow_dispatch always targets main's tip)
#   workflow_run_sha empty         -> exit 1 (no SHA resolved for the completed run)
#   workflow_run_sha != latest_main_sha
#                                   -> print nothing to stdout, log why to
#                                      stderr, exit 0 (STALE: a later push
#                                      already superseded this CI completion —
#                                      skip cleanly, not an error)
#   workflow_run_sha == latest_main_sha
#                                   -> print workflow_run_sha, exit 0
set -euo pipefail

event_name="${1:?event_name required}"
workflow_run_sha="${2:-}"
latest_main_sha="${3:?latest_main_sha required}"

if [[ "$event_name" != "workflow_run" ]]; then
  echo "$latest_main_sha"
  exit 0
fi

if [[ -z "$workflow_run_sha" ]]; then
  echo "No workflow_run head SHA resolved for report-branch-main deploy." >&2
  exit 1
fi

if [[ "$workflow_run_sha" != "$latest_main_sha" ]]; then
  echo "Skipping stale CI completion: workflow_run_sha=$workflow_run_sha latest_main_sha=$latest_main_sha" >&2
  exit 0
fi

echo "$workflow_run_sha"
