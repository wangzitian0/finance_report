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
    script = r'''
      source common/shell/common.sh
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


def test_AC8_13_72_deploy_script_logs_allowlisted_env_diff_only() -> None:
    deploy_script = (ROOT / "tools/_lib/shell/dokploy_deploy.sh").read_text()
    common_shell = (ROOT / "common/shell/common.sh").read_text()

    assert "render_allowlisted_env_diff" in deploy_script
    assert "IMAGE_TAG" in deploy_script
    assert "GIT_COMMIT_SHA" in deploy_script
    assert "IAC_CONFIG_HASH" in deploy_script
    assert "ENV_SUFFIX" in deploy_script
    assert "COMPOSE_PROFILES" in deploy_script
    assert "cat \"$response_file\"" in deploy_script
    assert "echo \"$current_env\"" not in deploy_script
    assert '-H "x-api-key: $DOKPLOY_API_KEY"' not in common_shell
    assert '-d "$data"' not in common_shell
    assert "--connect-timeout" in common_shell
    assert "--max-time" in common_shell
    assert "--config \"$curl_config_file\"" in common_shell
    assert "--data-binary \"@$data_file\"" in common_shell
