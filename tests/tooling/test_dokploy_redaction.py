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


def test_AC8_13_72_deploy_v2_updates_allowlisted_env_only() -> None:
    primitive = (ROOT / "repo/tools/deploy_primitive.py").read_text()
    common_shell = (ROOT / "common/shell/common.sh").read_text()

    assert "env_vars = {" in primitive
    for key in (
        "IMAGE_TAG",
        "GIT_COMMIT_SHA",
        "IAC_CONFIG_HASH",
        "ENV_SUFFIX",
        "COMPOSE_PROFILES",
        "TRAEFIK_ENABLE",
        "INTERNAL_DOMAIN",
    ):
        assert f'"{key}"' in primitive
    assert "client.update_compose_env(cfg.compose_id, env_vars=env_vars)" in primitive
    assert "print(env_vars)" not in primitive
    assert "client.get_compose_env" in primitive
    assert "print(client.get_compose_env" not in primitive
    assert '-H "x-api-key: $DOKPLOY_API_KEY"' not in common_shell
    assert '-d "$data"' not in common_shell
    assert "--connect-timeout" in common_shell
    assert "--max-time" in common_shell
    assert "--config \"$curl_config_file\"" in common_shell
    assert "--data-binary \"@$data_file\"" in common_shell


def test_AC8_13_72_deploy_v2_dokploy_client_does_not_log_raw_response_bodies() -> None:
    dokploy_client = (ROOT / "repo/libs/dokploy.py").read_text()
    primitive = (ROOT / "repo/tools/deploy_primitive.py").read_text()

    request_block = dokploy_client.split("def _request(", 1)[1].split(
        "    # Project endpoints", 1
    )[0]

    assert "resp.raise_for_status()" in request_block
    assert "status code {exc.response.status_code}" in request_block
    assert "{exc.response.reason_phrase}" in request_block
    error_block = request_block.split("except httpx.HTTPStatusError", 1)[1]
    assert "exc.response.text" not in error_block
    assert "resp.text" not in error_block
    assert "resp.content" not in error_block
    assert "headers" not in request_block.split("raise httpx.HTTPStatusError", 1)[1]
    assert "x-api-key" not in request_block.split("raise httpx.HTTPStatusError", 1)[1]

    assert "deploy rollout entered error" in primitive
    assert "deploy rollout did not finish" in primitive
    assert "client.get_compose_env" in primitive
    assert "print(client.get_compose_env" not in primitive
