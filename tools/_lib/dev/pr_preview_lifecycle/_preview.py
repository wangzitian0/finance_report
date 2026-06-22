"""Preview naming, URLs, ports, image tags, context + env build."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

from tools._lib.dev.pr_preview_lifecycle._base import (
    PR_PREVIEW_COMPOSE_PATH,
)
from tools._lib.dev.pr_preview_lifecycle._util import redact_diagnostic_value


def preview_compose_project(pr_number: int) -> str:
    return f"finance_report_pr_{pr_number}"


def preview_commit_slug(commit_sha: str) -> str:
    if not commit_sha:
        raise ValueError("commit_sha is required for PR preview routing")
    slug = re.sub(r"[^a-z0-9]+", "-", commit_sha.lower()).strip("-")
    if not slug:
        raise ValueError("commit_sha did not contain any URL-safe characters")
    return slug[:12]


def preview_env_suffix(pr_number: int, commit_sha: str) -> str:
    return f"-pr-{pr_number}-{preview_commit_slug(commit_sha)}"


def preview_stable_app_url(pr_number: int, internal_domain: str) -> str:
    return f"https://report-pr-{pr_number}.{internal_domain}"


def preview_commit_app_url(
    pr_number: int, commit_sha: str, internal_domain: str
) -> str:
    return (
        f"https://report{preview_env_suffix(pr_number, commit_sha)}.{internal_domain}"
    )


def preview_app_url(pr_number: int, commit_sha: str, internal_domain: str) -> str:
    return preview_stable_app_url(pr_number, internal_domain)


def preview_compose_command(project_name: str | None = None) -> str:
    # Build the PR's source on the Dokploy host (GitHub-source deploy) instead of
    # pulling a CI-pushed image. PR previews never push images; image building +
    # promotion happens only post-merge (deploy.yml target=staging). `--build` rebuilds the
    # backend/frontend contexts that the preview compose now declares.
    #
    # The `-p` project name MUST equal Dokploy's own appName for this compose.
    # Dokploy's compose.delete tears the stack down with `docker compose down`
    # scoped to appName; if `up` runs under a different project, delete removes
    # the Dokploy record but leaves the containers orphaned (no `docker compose
    # down` ever targets them, and nothing else reaps them). Callers pass the
    # appName via get_compose_app_name(); the project-less form is only a
    # create-time placeholder that update_compose_source() always overwrites
    # before any deploy.
    project_flag = f"-p {project_name} " if project_name else ""
    return (
        f"compose {project_flag}"
        f"-f {PR_PREVIEW_COMPOSE_PATH} up -d --build --remove-orphans"
    )


def preview_port_offset(pr_number: int, commit_sha: str) -> int:
    seed = f"{pr_number}:{preview_commit_slug(commit_sha)}"
    return sum((index + 1) * ord(char) for index, char in enumerate(seed)) % 1000


def preview_image_tag(pr_number: int, commit_sha: str) -> str:
    if not commit_sha:
        raise ValueError("commit_sha is required for PR preview image tags")
    return f"pr-{pr_number}-{commit_sha}"


def validate_deploy_inputs(args: argparse.Namespace) -> None:
    required_fields = (
        "pr_number",
        "compose_name",
        "environment_id",
        "api_url",
        "api_key",
        "github_integration_id",
        "branch",
        "commit_sha",
        "registry",
        "image_prefix",
        "internal_domain",
    )
    missing = [
        field
        for field in required_fields
        if not str(getattr(args, field, "") or "").strip()
    ]
    if missing:
        raise ValueError(
            "Missing required PR preview deploy inputs: " + ", ".join(sorted(missing))
        )
    if int(args.pr_number) <= 0:
        raise ValueError("PR preview deploy requires a positive pr_number")
    if "/" not in str(args.image_prefix):
        raise ValueError("PR preview image_prefix must include the registry namespace")
    if "." not in str(args.internal_domain):
        raise ValueError("PR preview internal_domain must be a DNS name")


def build_preview_context(
    args: argparse.Namespace,
    *,
    phase: str,
    compose_id: str = "",
    error: str = "",
    mutation_step: str = "",
    recovery_state: str = "",
) -> dict[str, str]:
    app_url = preview_app_url(args.pr_number, args.commit_sha, args.internal_domain)
    context = {
        "phase": phase,
        "pr_number": str(args.pr_number),
        "compose_name": str(args.compose_name),
        "compose_id": compose_id,
        "branch": str(args.branch),
        "commit_sha": str(args.commit_sha),
        "expected_sha": str(args.commit_sha),
        "commit_preview_app_url": preview_commit_app_url(
            args.pr_number,
            args.commit_sha,
            args.internal_domain,
        ),
        "preview_commit_slug": preview_commit_slug(str(args.commit_sha)),
        "image_tag": preview_image_tag(args.pr_number, args.commit_sha),
        "backend_image": f"{args.registry}/{args.image_prefix}-backend:{preview_image_tag(args.pr_number, args.commit_sha)}",
        "frontend_image": f"{args.registry}/{args.image_prefix}-frontend:{preview_image_tag(args.pr_number, args.commit_sha)}",
        "app_url": app_url,
        "api_health_url": f"{app_url}/api/health",
        "frontend_version_url": f"{app_url}/frontend-version.json?expected={args.commit_sha}",
        "dokploy_api_url": str(args.api_url).rstrip("/"),
        "environment_id": str(args.environment_id),
        "context_schema": "pr-preview-deploy-v1",
    }
    if error:
        context["error"] = redact_diagnostic_value(error)
    if mutation_step:
        context["mutation_step"] = mutation_step
    if recovery_state:
        context["recovery_state"] = recovery_state
    return context


def write_preview_context(path: str, context: dict[str, str]) -> None:
    if not path:
        return
    context_path = Path(path)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        json.dumps(context, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"PR preview deploy context written: {context_path}")


def build_preview_env(
    *,
    pr_number: int,
    commit_sha: str,
    registry: str,
    image_prefix: str,
    internal_domain: str,
) -> dict[str, str]:
    port_offset = preview_port_offset(pr_number, commit_sha)
    env_suffix = preview_env_suffix(pr_number, commit_sha)
    app_url = preview_app_url(pr_number, commit_sha, internal_domain)
    return {
        "PR_PREVIEW_PR_NUMBER": str(pr_number),
        "PR_PREVIEW_COMPOSE_NAME": f"pr-{pr_number}",
        # Informational label only. The real docker compose project is Dokploy's
        # appName (set via the `-p` flag in preview_compose_command); this stable
        # per-PR identifier is NOT wired to COMPOSE_PROJECT_NAME anymore.
        "PR_PREVIEW_COMPOSE_PROJECT": preview_compose_project(pr_number),
        "PR_PREVIEW_CREATED_BY": "github-actions",
        "GIT_COMMIT_SHA": commit_sha,
        "REGISTRY": registry,
        "IMAGE_PREFIX": image_prefix,
        "IMAGE_TAG": preview_image_tag(pr_number, commit_sha),
        "ENV_SUFFIX": env_suffix,
        "ENV_DOMAIN_SUFFIX": env_suffix,
        "NETWORK_SUFFIX": f"-pr-{pr_number}",
        "INTERNAL_DOMAIN": internal_domain,
        "TRAEFIK_ENABLE": "true",
        "NEXT_PUBLIC_API_URL": app_url,
        "NEXT_PUBLIC_APP_URL": app_url,
        "DEBUG": "true",
        "DB_PORTS": f"127.0.0.1:{30000 + port_offset}:5432",
        "MINIO_API_PORTS": f"127.0.0.1:{32000 + port_offset}:9000",
        "MINIO_CONSOLE_PORTS": f"127.0.0.1:{33000 + port_offset}:9001",
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
        "DB_HOST": f"finance-report-db{env_suffix}",
        "S3_HOST": f"finance-report-minio{env_suffix}",
        "S3_ENDPOINT": f"http://finance-report-minio{env_suffix}:9000",
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
