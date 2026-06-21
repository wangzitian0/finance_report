"""Shared constants, env-key policy, regex patterns."""

from __future__ import annotations

import re
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

ALLOWLIST_ENV_KEYS = (
    "IMAGE_TAG",
    "GIT_COMMIT_SHA",
    "IAC_CONFIG_HASH",
    "ENV_SUFFIX",
    "ENV_DOMAIN_SUFFIX",
    "NETWORK_SUFFIX",
    "NEXT_PUBLIC_API_URL",
    "DB_HOST",
    "S3_HOST",
    "COMPOSE_PROFILES",
)

# Keys that the platform (Dokploy / Vault-agent) injects or owns in the
# effective compose env. They legitimately appear in the effective env without
# being part of the deterministic requested preview env, so reconciliation must
# not treat them as stale drift (issue #758).
PLATFORM_MANAGED_ENV_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "VAULT_APP_TOKEN",
)
PLATFORM_MANAGED_ENV_PREFIXES = (
    "VAULT_",
    "DOKPLOY_",
)


def is_platform_managed_env_key(key: str) -> bool:
    return key in PLATFORM_MANAGED_ENV_KEYS or key.startswith(
        PLATFORM_MANAGED_ENV_PREFIXES
    )


COMPOSE_SUMMARY_KEYS = (
    "composeId",
    "name",
    "sourceType",
    "repository",
    "owner",
    "branch",
    "composePath",
    "command",
    "environmentId",
    "composeStatus",
    "status",
)
DEPLOYMENT_DIAGNOSTIC_KEYS = (
    "message",
    "error",
    "errorMessage",
    "statusMessage",
    "statusReason",
    "reason",
    "description",
    "logPath",
)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b("
    r"[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|AUTHORIZATION|COOKIE|"
    r"DATABASE_URL|REFRESH)[A-Z0-9_]*\s*[:=]\s*"
    r")([^,\s]+)"
)
AUTH_VALUE_PATTERN = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/\-]+=*")
VAULT_TOKEN_PATTERN = re.compile(r"\bhvs\.[A-Za-z0-9._-]+")

DEPLOYMENT_READY_FOR_READINESS_STATUSES = {"done"}
PR_PREVIEW_COMPOSE_PATH = "docker-compose.pr-preview.yml"
PR_PREVIEW_COMPOSE_TYPE = "docker-compose"
PR_PREVIEW_SOURCE_TYPE = "github"
PR_PREVIEW_REPOSITORY = "finance_report"
PR_PREVIEW_OWNER = "wangzitian0"
PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS = 120
PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV = (
    "PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS"
)
DOKPLOY_API_CONNECT_TIMEOUT_SECONDS = 10
DOKPLOY_API_MAX_TIME_SECONDS = 20
PR_PREVIEW_CONTEXT_ENV = "PR_PREVIEW_CONTEXT_PATH"
