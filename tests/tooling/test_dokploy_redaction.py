"""AC8.13.72: Dokploy deployment diagnostics redact unsafe responses."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_AC8_13_72_common_dokploy_call_redacts_non_200_body() -> None:
    """AC-testing.preview.4: Dokploy deploy diagnostics redact raw responses, log only
    allowlisted effective environment/config details, parse deployment records as typed
    object records, fail before readiness when fixed deploy_v2 sees rollout error/no
    terminal new record, and retain redacted rollout diagnostics for legacy preview
    compatibility (Was EPIC-008 AC8.13.72).
    """
    script = r'''
      source common/runtime/shell/common.sh
      DOKPLOY_API_URL="https://dokploy.example/api"
      DOKPLOY_API_KEY="api-secret"
      curl() {
        local output=""
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "-o" ]; then
            output="$2"
            shift 2
            continue
          fi
          shift
        done
        cat > "$output" <<'JSON'
{"message":"failed","refreshToken":"refresh-secret","env":"VAULT_APP_TOKEN=hvs.secret\nPASSWORD=pw-secret","nested":{"apiKey":"key-secret"}}
JSON
        printf "500"
      }
      output_file="$(mktemp)"
      dokploy_api_call "POST" "compose.update" '{"composeId":"cmp"}' "$output_file" "Environment update"
    '''

    result = run_bash(script)

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Environment update returned HTTP 500" in combined
    assert "safe_message: failed" in combined
    assert "raw_body_printed: false" in combined
    assert "refresh-secret" not in combined
    assert "hvs.secret" not in combined
    assert "pw-secret" not in combined
    assert "key-secret" not in combined
    assert "api-secret" not in combined
