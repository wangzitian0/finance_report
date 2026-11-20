"""Guards linking BACKGROUND_JOBS, main.py lifespan/CLI coverage, metrics, and DEPENDENCY_MANIFEST."""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "apps" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_background_jobs_manifest_and_main_coverage_policy() -> None:
    import src.main as main_module
    from src.observability import telemetry_metrics
    from src.runtime import BACKGROUND_JOBS

    job_names = [job.name for job in BACKGROUND_JOBS]
    cli_names = [job.cli_name for job in BACKGROUND_JOBS]
    assert len(job_names) == len(set(job_names)) >= 4
    assert len(cli_names) == len(set(cli_names))

    assert set(main_module.BACKGROUND_JOB_LOOPS) == set(job_names)
    assert set(main_module.BACKGROUND_JOB_ONCE) == set(job_names)

    registered_metrics = {
        *(name for _k, name, _d in telemetry_metrics._COUNTER_SPECS),
        *(name for _k, name, _d in telemetry_metrics._HISTOGRAM_SPECS),
    }
    for job in BACKGROUND_JOBS:
        assert job.failure_metric in registered_metrics, (
            f"Background job {job.name!r} failure_metric {job.failure_metric!r} is missing from telemetry_metrics"
        )

    main_source = (BACKEND_DIR / "src" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_source)
    task_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert len(task_calls) == 1, (
        f"main.py must only call create_task inside BACKGROUND_JOBS loop, found lines: {task_calls}"
    )

    pyproject = tomllib.loads(
        (BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )
    omit = pyproject["tool"]["coverage"]["run"]["omit"]
    assert "main.py" not in omit, (
        "apps/backend/pyproject.toml must not omit main.py from coverage"
    )


def test_cli_job_lists_every_background_job() -> None:
    from src.runtime import BACKGROUND_JOBS

    proc = subprocess.run(
        [
            str(BACKEND_DIR / ".venv" / "bin" / "python"),
            "tools/cli.py",
            "job",
            "--list",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for job in BACKGROUND_JOBS:
        assert job.cli_name in proc.stdout
        assert job.concurrency in proc.stdout

    bad_proc = subprocess.run(
        [
            str(BACKEND_DIR / ".venv" / "bin" / "python"),
            "tools/cli.py",
            "job",
            "--run-once",
            "missing-job",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert bad_proc.returncode != 0


def test_every_declared_dependency_has_non_runtime_consumer() -> None:
    from src.runtime import DEPENDENCY_MANIFEST

    expected_consumers = {
        "database": ("async_session_maker", "get_db", "SQLAlchemy"),
        "object_storage": ("StorageService",),
        "llm": ("settings.ai_provider", "to_llm_settings", "ai_api_key"),
        "cache": ("redis_url", "is_allowed_async"),
        "workflow_engine": ("prefect_api_url",),
        "telemetry": ("otel_exporter_otlp_endpoint",),
        "analytics": ("openpanel_api_url", "openpanel_client_id"),
        "market_data": ("market_data_yahoo_timeout_seconds",),
    }
    assert set(expected_consumers) == DEPENDENCY_MANIFEST.names()

    src_texts: list[tuple[str, str]] = []
    for path in sorted((BACKEND_DIR / "src").rglob("*.py")):
        rel = path.relative_to(BACKEND_DIR / "src").as_posix()
        if rel in {"boot.py", "config.py"} or rel.startswith(("runtime/", "schemas/")):
            continue
        src_texts.append((rel, path.read_text(encoding="utf-8")))

    combined = "\n".join(text for _, text in src_texts)
    missing = [
        dep_name
        for dep_name, markers in expected_consumers.items()
        if not any(marker in combined for marker in markers)
    ]
    assert missing == [], (
        f"DEPENDENCY_MANIFEST entries with zero runtime consumers outside boot/runtime: {missing}"
    )
