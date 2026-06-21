"""AC8.13.38 AC8.13.74: legacy cleanup entrypoint is fully retired."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_38_legacy_cleanup_entrypoints_are_removed() -> None:
    assert not (ROOT / "tools/cleanup_pr_preview_resources.py").exists()
    assert not (ROOT / "tools/_lib/dev/cleanup_pr_preview_resources.py").exists()


def test_AC8_13_38_pr_preview_lifecycle_has_no_host_hygiene_commands() -> None:
    module = "\n# <<< file-boundary >>>\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "tools/_lib/dev/pr_preview_lifecycle").rglob("*.py"))
    )

    assert "docker builder prune" not in module
    assert "docker image prune" not in module
    assert "docker container prune" not in module
    assert "journalctl" not in module
    assert "ssh" not in module
    assert "VPS_SSH_KEY" not in module
    assert "DOKPLOY_API_KEY" not in module


def test_AC8_13_74_workflow_runs_lifecycle_reconciliation_only() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert 'cron: "37 */6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "tools/pr_preview_lifecycle.py" in workflow
    assert "--action reconcile" in workflow
    assert "tools/cleanup_pr_preview_resources.py" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journal-vacuum" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow


def test_AC8_13_38_pr_preview_compose_caps_docker_json_logs() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "x-json-logging: &json-logging" in compose
    assert "driver: json-file" in compose
    assert 'max-size: "${DOCKER_LOG_MAX_SIZE:-10m}"' in compose
    assert 'max-file: "${DOCKER_LOG_MAX_FILE:-3}"' in compose

    lines = compose.splitlines()
    for service in ["postgres", "minio", "minio-init", "backend", "frontend"]:
        start = lines.index(f"  {service}:")
        block_lines: list[str] = []
        for line in lines[start + 1 :]:
            if line.startswith("  ") and not line.startswith("    "):
                break
            block_lines.append(line)
        service_block = "\n".join(block_lines)
        assert "logging: *json-logging" in service_block
