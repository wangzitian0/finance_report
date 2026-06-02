#!/usr/bin/env python3
"""Own PR preview create/update/deploy, close cleanup, and reconciliation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

ALLOWLIST_ENV_KEYS = (
    "IMAGE_TAG",
    "GIT_COMMIT_SHA",
    "IAC_CONFIG_HASH",
    "ENV_SUFFIX",
    "COMPOSE_PROFILES",
)
SAFE_COMPOSE_PROJECT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class DokployConfig:
    api_url: str
    api_key: str


def run_command(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def ssh_command(
    host: str, user: str, ssh_key: str | None, remote_command: str
) -> list[str]:
    cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if ssh_key:
        cmd.extend(["-i", ssh_key])
    cmd.append(f"{user}@{host}")
    cmd.append(remote_command)
    return cmd


def parse_env(env_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def render_env(env: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in env.items()) + "\n"


def allowlisted_env_matches(expected: dict[str, str], actual_env_text: str) -> bool:
    actual = parse_env(actual_env_text)
    return all(expected.get(key, "") == actual.get(key, "") for key in ALLOWLIST_ENV_KEYS)


def render_allowlisted_env_diff(expected: dict[str, str], actual_env_text: str) -> str:
    actual = parse_env(actual_env_text)
    lines = ["Effective deploy env diff"]
    for key in ALLOWLIST_ENV_KEYS:
        expected_value = expected.get(key, "")
        actual_value = actual.get(key, "")
        if expected_value == actual_value:
            lines.append(f"{key}: match")
        else:
            lines.append(f"{key}: expected={expected_value} actual={actual_value}")
    lines.append(
        f"result: {'match' if allowlisted_env_matches(expected, actual_env_text) else 'mismatch'}"
    )
    lines.append("raw_env_printed: false")
    return "\n".join(lines)


def preview_compose_project(pr_number: int) -> str:
    return f"finance_report_pr_{pr_number}"


def build_preview_env(
    *,
    pr_number: int,
    commit_sha: str,
    registry: str,
    image_prefix: str,
    internal_domain: str,
) -> dict[str, str]:
    pr_mod = pr_number % 1000
    return {
        "PR_PREVIEW_PR_NUMBER": str(pr_number),
        "PR_PREVIEW_COMPOSE_NAME": f"pr-{pr_number}",
        "PR_PREVIEW_COMPOSE_PROJECT": preview_compose_project(pr_number),
        "PR_PREVIEW_CREATED_BY": "github-actions",
        "GIT_COMMIT_SHA": commit_sha,
        "REGISTRY": registry,
        "IMAGE_PREFIX": image_prefix,
        "IMAGE_TAG": f"pr-{pr_number}",
        "COMPOSE_PROJECT_NAME": preview_compose_project(pr_number),
        "ENV_SUFFIX": f"-pr-{pr_number}",
        "ENV_DOMAIN_SUFFIX": f"-pr-{pr_number}",
        "INTERNAL_DOMAIN": internal_domain,
        "TRAEFIK_ENABLE": "true",
        "NEXT_PUBLIC_API_URL": f"https://report-pr-{pr_number}.{internal_domain}",
        "NEXT_PUBLIC_APP_URL": f"https://report-pr-{pr_number}.{internal_domain}",
        "DEBUG": "true",
        "DB_PORTS": f"127.0.0.1:{30000 + pr_mod}:5432",
        "MINIO_API_PORTS": f"127.0.0.1:{32000 + pr_mod}:9000",
        "MINIO_CONSOLE_PORTS": f"127.0.0.1:{33000 + pr_mod}:9001",
        "AI_PROVIDER": "zai",
        "ZAI_API_KEY": "",
        "AI_BASE_URL": "https://api.z.ai/api/coding/paas/v4",
        "AI_CHAT_COMPLETIONS_PATH": "/chat/completions",
        "AI_LAYOUT_PARSING_PATH": "/layout_parsing",
        "AI_MODEL_CATALOG_SOURCE": "configured",
        "PRIMARY_MODEL": "glm-5.1",
        "OCR_MODEL": "glm-4.6v",
        "VISION_MODEL": "glm-4.6v",
        "FALLBACK_MODELS": "glm-5-turbo,glm-5",
        "AI_JSON_TIMEOUT_SECONDS": "360",
        "AI_JSON_MAX_TOKENS": "8192",
        "AI_JSON_DISABLE_THINKING": "true",
        "COMPOSE_PROFILES": "infra,app",
        "DB_HOST": f"finance-report-db-pr-{pr_number}",
        "S3_HOST": f"finance-report-minio-pr-{pr_number}",
        "S3_ENDPOINT": f"http://finance-report-minio-pr-{pr_number}:9000",
        "MINIO_ROOT_USER": "minio",
        "MINIO_ROOT_PASSWORD": "minio_local_secret",
        "S3_ACCESS_KEY": "minio",
        "S3_SECRET_KEY": "minio_local_secret",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://platform-signoz-otel-collector:4318",
        "OTEL_SERVICE_NAME": "finance-report-backend",
        "OTEL_RESOURCE_ATTRIBUTES": f"deployment.environment=pr-{pr_number}",
        "API_RATE_LIMIT_REQUESTS": "10000",
        "REGISTER_RATE_LIMIT_REQUESTS": "10000",
        "IAC_CONFIG_HASH": f"pr-{pr_number}-{commit_sha}",
    }


def _safe_message(body: str) -> str:
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        return "unavailable"
    for key in ("message", "error", "status"):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            return value[:160]
    return "unavailable"


def dokploy_api_call(
    config: DokployConfig,
    method: str,
    endpoint: str,
    *,
    payload: dict[str, object] | None = None,
    expected_status: int = 200,
) -> str:
    config_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    data_file: tempfile.NamedTemporaryFile[str] | None = None
    config_path = config_file.name
    data_path = ""
    escaped_api_key = config.api_key.replace("\\", "\\\\").replace('"', '\\"')
    config_file.write(f'header = "x-api-key: {escaped_api_key}"\n')
    config_file.close()

    cmd = [
        "curl",
        "-sS",
        "--max-time",
        "60",
        "--config",
        config_path,
        "-w",
        "\n%{http_code}",
    ]
    try:
        if method == "POST":
            cmd.extend(["-X", "POST", "-H", "Content-Type: application/json"])
            if payload is not None:
                data_file = tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False
                )
                data_path = data_file.name
                json.dump(payload, data_file)
                data_file.close()
                cmd.extend(["--data-binary", f"@{data_path}"])
        cmd.append(f"{config.api_url.rstrip('/')}/{endpoint}")

        result = run_command(cmd, check=False)
    finally:
        os.unlink(config_path)
        if data_path:
            os.unlink(data_path)
    body, _, status_text = result.stdout.rpartition("\n")
    try:
        status = int(status_text.strip())
    except ValueError:
        status = expected_status if result.returncode == 0 else 0
        body = result.stdout
    if result.returncode != 0 or status != expected_status:
        print(f"Dokploy request failed: endpoint={endpoint}", file=sys.stderr)
        print(f"http_code: {status or '000'}", file=sys.stderr)
        print(f"safe_message: {_safe_message(body)}", file=sys.stderr)
        print("raw_body_printed: false", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        raise RuntimeError(f"Dokploy request failed for {endpoint}")
    return body


def find_compose_id_by_name(
    config: DokployConfig, environment_id: str, compose_name: str
) -> str | None:
    body = dokploy_api_call(
        config,
        "GET",
        f"environment.one?environmentId={environment_id}",
    )
    data = json.loads(body or "{}")
    for compose in data.get("compose", []):
        if compose.get("name") == compose_name:
            compose_id = compose.get("composeId")
            return str(compose_id) if compose_id else None
    return None


def create_compose(
    config: DokployConfig,
    *,
    environment_id: str,
    compose_name: str,
    pr_number: int,
) -> str:
    body = dokploy_api_call(
        config,
        "POST",
        "compose.create",
        payload={
            "name": compose_name,
            "description": f"PR #{pr_number}: {compose_name}",
            "environmentId": environment_id,
        },
    )
    compose_id = json.loads(body or "{}").get("composeId")
    if not compose_id:
        raise RuntimeError("Dokploy compose.create response did not include composeId")
    print(f"Created compose: {compose_id}")
    return str(compose_id)


def get_or_create_compose(
    config: DokployConfig,
    *,
    environment_id: str,
    compose_name: str,
    pr_number: int,
) -> str:
    compose_id = find_compose_id_by_name(config, environment_id, compose_name)
    if compose_id:
        print(f"Found existing compose: {compose_id}")
        return compose_id
    return create_compose(
        config,
        environment_id=environment_id,
        compose_name=compose_name,
        pr_number=pr_number,
    )


def update_compose_source(
    config: DokployConfig,
    *,
    compose_id: str,
    branch: str,
    github_integration_id: str,
) -> None:
    dokploy_api_call(
        config,
        "POST",
        "compose.update",
        payload={
            "composeId": compose_id,
            "sourceType": "github",
            "repository": "finance_report",
            "owner": "wangzitian0",
            "branch": branch,
            "composePath": "docker-compose.yml",
            "githubId": github_integration_id,
        },
    )
    print(f"GitHub source configured for compose: {compose_id}")


def get_compose_env(config: DokployConfig, *, compose_id: str) -> str:
    body = dokploy_api_call(
        config,
        "GET",
        f"compose.one?composeId={compose_id}",
    )
    data = json.loads(body or "{}")
    env = data.get("env", "")
    return str(env) if env else ""


def update_compose_env(config: DokployConfig, *, compose_id: str, env: dict[str, str]) -> None:
    expected = {key: env[key] for key in ALLOWLIST_ENV_KEYS}
    dokploy_api_call(
        config,
        "POST",
        "compose.update",
        payload={"composeId": compose_id, "env": render_env(env)},
    )
    effective_env = get_compose_env(config, compose_id=compose_id)
    print(render_allowlisted_env_diff(expected, effective_env))
    if not allowlisted_env_matches(expected, effective_env):
        raise RuntimeError("Dokploy effective environment did not match requested deploy env")
    print(f"Environment variables configured for compose: {compose_id}")


def deploy_compose(config: DokployConfig, *, compose_id: str) -> None:
    dokploy_api_call(
        config,
        "POST",
        "compose.deploy",
        payload={"composeId": compose_id},
    )
    print(f"Deployment triggered for compose: {compose_id}")


def delete_compose(config: DokployConfig, *, compose_id: str) -> None:
    dokploy_api_call(
        config,
        "POST",
        "compose.delete",
        payload={"composeId": compose_id},
    )
    print(f"Compose deleted: {compose_id}")


def build_preview_cleanup_script(
    *,
    pr_number: int,
    compose_project: str,
    dry_run: bool,
) -> str:
    if not SAFE_COMPOSE_PROJECT_RE.match(compose_project):
        raise ValueError(f"Unsafe compose project: {compose_project}")
    mode = "echo [dry-run]" if dry_run else ""
    return "\n".join(
        [
            "set -eu",
            f"PR_NUMBER='{pr_number}'",
            f"COMPOSE_PROJECT='{compose_project}'",
            f'echo "Cleaning PR preview resources for #${{PR_NUMBER}}"',
            (
                'docker ps -a --format "{{.Names}}" | grep -E '
                f'"^finance-report-(backend|frontend|db|minio)-pr-{pr_number}$" '
                f"| xargs -r {mode} docker rm -f"
            ),
            (
                f'docker volume ls --format "{{{{.Name}}}}" | grep -E "^{compose_project}_" '
                f"| xargs -r {mode} docker volume rm"
            ),
            "",
        ]
    )


def cleanup_preview_volumes(
    *,
    host: str,
    user: str,
    ssh_key: str | None,
    pr_number: int,
    compose_project: str,
    dry_run: bool,
) -> int:
    script = build_preview_cleanup_script(
        pr_number=pr_number,
        compose_project=compose_project,
        dry_run=dry_run,
    )
    result = run_command(
        ssh_command(host, user, ssh_key, "sh -s"),
        input_text=script,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def deploy_action(args: argparse.Namespace) -> int:
    config = DokployConfig(api_url=args.api_url, api_key=args.api_key)
    compose_id = get_or_create_compose(
        config,
        environment_id=args.environment_id,
        compose_name=args.compose_name,
        pr_number=args.pr_number,
    )
    update_compose_source(
        config,
        compose_id=compose_id,
        branch=args.branch,
        github_integration_id=args.github_integration_id,
    )
    update_compose_env(
        config,
        compose_id=compose_id,
        env=build_preview_env(
            pr_number=args.pr_number,
            commit_sha=args.commit_sha,
            registry=args.registry,
            image_prefix=args.image_prefix,
            internal_domain=args.internal_domain,
        ),
    )
    deploy_compose(config, compose_id=compose_id)
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as output:
            output.write(f"compose_id={compose_id}\n")
    else:
        print(f"compose_id={compose_id}")
    return 0


def cleanup_action(args: argparse.Namespace) -> int:
    config = DokployConfig(api_url=args.api_url, api_key=args.api_key)
    compose_id = args.compose_id or find_compose_id_by_name(
        config,
        args.environment_id,
        args.compose_name,
    )
    if compose_id:
        delete_compose(config, compose_id=compose_id)
    else:
        print(f"Compose not found: {args.compose_name}")
    return cleanup_preview_volumes(
        host=args.host,
        user=args.user,
        ssh_key=args.ssh_key,
        pr_number=args.pr_number,
        compose_project=preview_compose_project(args.pr_number),
        dry_run=args.dry_run,
    )


def delete_action(args: argparse.Namespace) -> int:
    config = DokployConfig(api_url=args.api_url, api_key=args.api_key)
    compose_id = args.compose_id or find_compose_id_by_name(
        config,
        args.environment_id,
        args.compose_name,
    )
    if not compose_id:
        print(f"Compose not found: {args.compose_name}")
        return 0
    delete_compose(config, compose_id=compose_id)
    return 0


def parse_open_pr_numbers(output: str) -> set[int]:
    return {int(line.strip()) for line in output.splitlines() if line.strip()}


def list_open_pr_numbers() -> set[int]:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number",
            "--jq",
            ".[].number",
        ]
    )
    return parse_open_pr_numbers(result.stdout)


def list_remote_preview_prs(host: str, user: str, ssh_key: str | None) -> set[int]:
    result = run_command(
        ssh_command(
            host,
            user,
            ssh_key,
            "docker ps -a --format '{{.Names}}' | sed -n 's/^finance-report-[^-]*-pr-\\([0-9][0-9]*\\)$/\\1/p' | sort -nu",
        )
    )
    return parse_open_pr_numbers(result.stdout)


def reconcile_action(args: argparse.Namespace) -> int:
    open_prs = list_open_pr_numbers()
    remote_prs = list_remote_preview_prs(args.host, args.user, args.ssh_key)
    stale_prs = sorted(remote_prs - open_prs)
    print(f"Open PRs: {sorted(open_prs)}")
    print(f"Preview PRs on VPS: {sorted(remote_prs)}")
    print(f"Stale preview PRs: {stale_prs}")
    config = DokployConfig(api_url=args.api_url, api_key=args.api_key)
    result_code = 0
    for pr_number in stale_prs:
        compose_name = f"pr-{pr_number}"
        compose_id = find_compose_id_by_name(config, args.environment_id, compose_name)
        if compose_id:
            delete_compose(config, compose_id=compose_id)
        result_code = max(
            result_code,
            cleanup_preview_volumes(
                host=args.host,
                user=args.user,
                ssh_key=args.ssh_key,
                pr_number=pr_number,
                compose_project=preview_compose_project(pr_number),
                dry_run=args.dry_run,
            ),
        )
    return result_code


def main_from_args(args: argparse.Namespace) -> int:
    if args.action == "deploy":
        return deploy_action(args)
    if args.action == "delete":
        return delete_action(args)
    if args.action == "cleanup":
        return cleanup_action(args)
    if args.action == "reconcile":
        return reconcile_action(args)
    raise ValueError(f"Unsupported action: {args.action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=["deploy", "delete", "cleanup", "reconcile"], required=True
    )
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--compose-name", required=True)
    parser.add_argument("--compose-id", default="")
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--github-integration-id", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--registry", default="ghcr.io")
    parser.add_argument("--image-prefix", default="")
    parser.add_argument("--internal-domain", default="zitian.party")
    parser.add_argument("--host", default="cloud.zitian.party")
    parser.add_argument("--user", default="root")
    parser.add_argument("--ssh-key")
    parser.add_argument("--dry-run", action="store_true")
    return main_from_args(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
