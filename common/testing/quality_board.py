"""Generate the live, freshness-tracked finance_report quality dashboard (#3215 Slice 2C).

This module uses the Python standard library only so `.github/workflows/docs.yml`
can build `site/board/index.html` and `site/board/data.json` without installing
application or SDK wheels.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "finance-report-quality-board/1.0"
GITHUB_API_BASE = "https://api.github.com"

UTC8 = timedelta(hours=8)
WARN_AUDIT_AGE_HOURS = 36.0
CRITICAL_AUDIT_AGE_HOURS = 72.0
WARN_CI_AGE_HOURS = 48.0
CRITICAL_CI_AGE_HOURS = 96.0

DEFAULT_FINANCE_REPO = "wangzitian0/finance_report"
DEFAULT_INFRA2_REPO = "wangzitian0/infra2"
DEFAULT_STAGING_HEALTH_URL = "https://report-staging.zitian.party/api/health?full=1"
DEFAULT_PROD_HEALTH_URL = "https://report.zitian.party/api/health?full=1"

_PRE_NEEDS = frozenset({"code", "recorded_llm"})
_SCHEDULED_AUDIT_CAPABILITIES = frozenset(
    {"code", "staging_data", "running_service", "real_provider", "real_llm"}
)

HttpOpener = Callable[[urllib.request.Request, float], Any]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Stop urllib from forwarding GitHub Authorization headers onto Azure/blob 302 targets."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def default_opener(request: urllib.request.Request, timeout: float = 15.0) -> Any:
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


def _github_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def parse_iso_utc(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_utc8(dt: datetime) -> str:
    return (dt.astimezone(UTC) + UTC8).strftime("%Y-%m-%d %H:%M:%S UTC+8")


def _fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str],
    opener: HttpOpener = default_opener,
    timeout: float = 15.0,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener(request, timeout) as resp:
            status = int(getattr(resp, "status", resp.getcode()))
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return status, resp_headers, resp.read()
    except urllib.error.HTTPError as err:
        if err.code in (301, 302, 303, 307, 308):
            location = err.headers.get("Location") if err.headers else None
            if not location:
                raise
            # Signed Azure blob / GitHub release redirect target rejects Authorization headers.
            stripped_headers = {"User-Agent": headers.get("User-Agent", USER_AGENT)}
            redirect_req = urllib.request.Request(
                location, headers=stripped_headers, method="GET"
            )
            with opener(redirect_req, timeout) as resp2:
                status2 = int(getattr(resp2, "status", resp2.getcode()))
                headers2 = {k.lower(): v for k, v in resp2.headers.items()}
                return status2, headers2, resp2.read()
        raise


def fetch_github_json(
    path: str,
    *,
    token: str = "",
    opener: HttpOpener = default_opener,
    timeout: float = 15.0,
) -> Any:
    url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"
    _status, _headers, body = _fetch_bytes(
        url, headers=_github_headers(token), opener=opener, timeout=timeout
    )
    return json.loads(body.decode("utf-8"))


def download_artifact_files(
    archive_url: str,
    *,
    token: str = "",
    opener: HttpOpener = default_opener,
    timeout: float = 30.0,
) -> dict[str, bytes]:
    """Download a GitHub Actions artifact zip archive into `{member_name: raw_bytes}`."""
    _status, _headers, payload = _fetch_bytes(
        archive_url, headers=_github_headers(token), opener=opener, timeout=timeout
    )
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            if not info.is_dir():
                out[info.filename] = zf.read(info.filename)
    return out


def expected_scheduled_audit_checks(manifest_path: Path) -> tuple[str, ...]:
    """Derive active `scheduled_audit` check IDs from schema-3 `runtime-hooks.manifest.json`."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    active: list[str] = []
    for row in data.get("checks", []):
        cid = str(row.get("id") or "").strip()
        if not cid or cid == "smoke":
            continue
        needs = {str(n) for n in row.get("needs", ())}
        if needs <= _PRE_NEEDS:
            default_in_audit = False
        else:
            default_in_audit = needs <= _SCHEDULED_AUDIT_CAPABILITIES
        cells = row.get("cells") or {}
        removed = cells.get("remove") or {}
        added = cells.get("add") or {}
        if (default_in_audit and "scheduled_audit" not in removed) or (
            "scheduled_audit" in added
        ):
            active.append(cid)
    return tuple(active)


def collect_user_cases(ssot_path: Path) -> dict[str, Any]:
    """Summarize the 47-user-case SSOT registry without duplicating per-test tables."""
    data = json.loads(ssot_path.read_text(encoding="utf-8"))
    domains_out: list[dict[str, Any]] = []
    total = 0
    gap_counts: dict[str, int] = {"complete": 0, "partial": 0, "missing": 0}
    ref_counts: dict[str, int] = {
        "backend_test_ref": 0,
        "frontend_test_ref": 0,
        "e2e_test_ref": 0,
        "benchmark_cases": 0,
    }
    for domain in data.get("domains", []):
        cases = domain.get("user_cases", [])
        domain_gaps: dict[str, int] = {"complete": 0, "partial": 0, "missing": 0}
        e2e_cnt = 0
        bench_cnt = 0
        for uc in cases:
            total += 1
            raw_gap = uc.get("gap_kind")
            gap_key = (
                "complete"
                if raw_gap in (None, "", "none", "complete")
                else ("partial" if raw_gap == "partial" else "missing")
            )
            gap_counts[gap_key] = gap_counts.get(gap_key, 0) + 1
            domain_gaps[gap_key] = domain_gaps.get(gap_key, 0) + 1
            for field in ("backend_test_ref", "frontend_test_ref", "e2e_test_ref"):
                if uc.get(field):
                    ref_counts[field] += 1
            if uc.get("e2e_test_ref"):
                e2e_cnt += 1
            if uc.get("benchmark_cases"):
                ref_counts["benchmark_cases"] += 1
                bench_cnt += 1
        domains_out.append(
            {
                "id": domain.get("id"),
                "name": str(domain.get("name") or ""),
                "total": len(cases),
                "complete": domain_gaps["complete"],
                "partial": domain_gaps["partial"],
                "missing": domain_gaps["missing"],
                "e2e_linked": e2e_cnt,
                "benchmark_linked": bench_cnt,
            }
        )
    return {
        "version": str(data.get("version") or ""),
        "total": total,
        "gaps": gap_counts,
        "refs": ref_counts,
        "domains": domains_out,
    }


def probe_runtime_health(
    url: str,
    *,
    label: str,
    opener: HttpOpener = default_opener,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Read-only probe of `/api/health?full=1`; never suppresses errors."""
    started = time.monotonic()
    try:
        status_code, _headers, raw = _fetch_bytes(
            url, headers={"User-Agent": USER_AGENT}, opener=opener, timeout=timeout
        )
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        payload = json.loads(raw.decode("utf-8"))
        raw_checks = payload.get("checks") or {}
        checks_out: dict[str, dict[str, Any]] = {}
        for name, entry in sorted(raw_checks.items()):
            if isinstance(entry, Mapping):
                checks_out[str(name)] = {
                    "status": str(entry.get("status") or "unknown"),
                    "required": bool(entry.get("required", True)),
                    "detail": str(entry.get("detail") or "")[:180],
                    "duration_ms": round(float(entry.get("duration_ms") or 0.0), 1),
                }
        return {
            "env": label,
            "url": url,
            "reachable": True,
            "http_status": status_code,
            "status": str(payload.get("status") or "unknown"),
            "version": str(payload.get("version") or "unknown"),
            "timestamp": str(payload.get("timestamp") or ""),
            "latency_ms": latency_ms,
            "checks": checks_out,
            "reasons": list(payload.get("reasons") or ()),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - network/HTTP/JSON failures surface honestly
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        return {
            "env": label,
            "url": url,
            "reachable": False,
            "http_status": None,
            "status": "error",
            "version": "unknown",
            "timestamp": "",
            "latency_ms": latency_ms,
            "checks": {},
            "reasons": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_ci_post(
    repo: str,
    *,
    token: str = "",
    opener: HttpOpener = default_opener,
    limit: int = 15,
) -> dict[str, Any]:
    """Collect recent `ci-post-telemetry` artifacts and fallback `main` CI run summaries."""
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        listing = fetch_github_json(
            f"/repos/{repo}/actions/artifacts?name=ci-post-telemetry&per_page=30",
            token=token,
            opener=opener,
        )
        artifacts = [
            a for a in (listing.get("artifacts") or ()) if not a.get("expired")
        ]
        main_artifacts = [
            a
            for a in artifacts
            if (a.get("workflow_run") or {}).get("head_branch") in (None, "main")
        ]
        selected = main_artifacts[:limit]
        for art in selected:
            try:
                files = download_artifact_files(
                    str(art["archive_download_url"]), token=token, opener=opener
                )
                raw = files.get("ci-post-telemetry.json")
                if raw is None:
                    raw = next(
                        (v for k, v in files.items() if k.endswith(".json")), None
                    )
                if raw is None:
                    continue
                payload = json.loads(raw.decode("utf-8"))
                timing = payload.get("timing") or {}
                budget = timing.get("budget") or {}
                cov = payload.get("coverage") or {}
                runs.append(
                    {
                        "run_id": str(payload.get("run_id") or (art.get("workflow_run") or {}).get("id") or ""),
                        "run_url": str(payload.get("run_url") or ""),
                        "sha": str(payload.get("sha") or "")[:7],
                        "ref": str(payload.get("ref") or ""),
                        "generated_at_utc": str(payload.get("generated_at_utc") or art.get("created_at") or ""),
                        "execution_seconds": timing.get("execution_seconds"),
                        "budget_seconds": budget.get("budget_seconds"),
                        "budget_state": budget.get("state"),
                        "backend": cov.get("backend"),
                        "frontend": cov.get("frontend"),
                        "jobs": payload.get("jobs") or {},
                    }
                )
            except Exception as exc:  # noqa: BLE001 - continue collecting remaining runs
                errors.append(f"artifact {art.get('id')}: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ci-post-telemetry listing failed: {type(exc).__name__}: {exc}")

    recent_main_runs: list[dict[str, Any]] = []
    try:
        wf = fetch_github_json(
            f"/repos/{repo}/actions/workflows/ci.yml/runs?branch=main&status=completed&per_page=8",
            token=token,
            opener=opener,
        )
        for r in wf.get("workflow_runs") or ():
            recent_main_runs.append(
                {
                    "id": str(r.get("id") or ""),
                    "sha": str(r.get("head_sha") or "")[:7],
                    "conclusion": str(r.get("conclusion") or "unknown"),
                    "created_at": str(r.get("created_at") or ""),
                    "updated_at": str(r.get("updated_at") or ""),
                    "url": str(r.get("html_url") or ""),
                }
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ci.yml runs query failed: {type(exc).__name__}: {exc}")

    latest_ts = runs[0]["generated_at_utc"] if runs else None
    return {
        "repo": repo,
        "artifacts_count": len(runs),
        "latest_at_utc": latest_ts,
        "latest": runs[0] if runs else None,
        "runs": runs,
        "recent_main_runs": recent_main_runs,
        "errors": errors,
    }


def _find_finance_audit_entry(audit_json: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in audit_json.get("scheduled_audit_results") or ():
        if isinstance(item, Mapping) and item.get("service") == "finance_report/app":
            return item
    return None


def collect_scheduled_audit(
    infra2_repo: str,
    *,
    expected_checks: Sequence[str],
    token: str = "",
    opener: HttpOpener = default_opener,
    limit: int = 7,
) -> dict[str, Any]:
    """Collect recent `scheduled-audit-results` artifacts and stage records from `infra2`."""
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        listing = fetch_github_json(
            f"/repos/{infra2_repo}/actions/artifacts?name=scheduled-audit-results&per_page=15",
            token=token,
            opener=opener,
        )
        artifacts = [
            a for a in (listing.get("artifacts") or ()) if not a.get("expired")
        ][:limit]
        for art in artifacts:
            wf_run = art.get("workflow_run") or {}
            run_id = str(wf_run.get("id") or "")
            run_url = (
                f"https://github.com/{infra2_repo}/actions/runs/{run_id}"
                if run_id
                else ""
            )
            try:
                files = download_artifact_files(
                    str(art["archive_download_url"]), token=token, opener=opener
                )
                raw_result = files.get("scheduled-audit-result.json")
                audit_payload = (
                    json.loads(raw_result.decode("utf-8")) if raw_result else {}
                )
                entry = _find_finance_audit_entry(audit_payload) or {}
                raw_checks = [
                    {
                        "name": str(c.get("name") or ""),
                        "ok": False if c.get("skipped") else bool(c.get("ok")),
                        "skipped": bool(c.get("skipped")),
                        "seconds": round(float(c.get("seconds") or 0.0), 2),
                        "detail": str(c.get("detail") or "")[:200],
                    }
                    for c in (entry.get("checks") or ())
                    if isinstance(c, Mapping)
                ]
                oracle_summaries = dict(entry.get("oracle_summaries") or {})
                for fname, raw_bytes in sorted(files.items()):
                    if (
                        "finance_report_app/" in fname
                        and fname.endswith(".json")
                        and "summary" in Path(fname).name
                    ):
                        stem = Path(fname).stem
                        if stem not in oracle_summaries:
                            try:
                                oracle_summaries[stem] = json.loads(
                                    raw_bytes.decode("utf-8")
                                )
                            except ValueError:
                                pass
                stage_record_status: str | None = None
                if run_id:
                    try:
                        run_arts = fetch_github_json(
                            f"/repos/{infra2_repo}/actions/runs/{run_id}/artifacts",
                            token=token,
                            opener=opener,
                        )
                        for ra in run_arts.get("artifacts") or ():
                            if (
                                str(ra.get("name") or "").startswith(
                                    "stage-staging.provider_regression-"
                                )
                                and not ra.get("expired")
                            ):
                                rec_files = download_artifact_files(
                                    str(ra["archive_download_url"]),
                                    token=token,
                                    opener=opener,
                                )
                                first_rec = next(iter(rec_files.values()), None)
                                if first_rec:
                                    rec_json = json.loads(first_rec.decode("utf-8"))
                                    stage_record_status = str(
                                        rec_json.get("verdict") or ""
                                    )
                                break
                    except Exception:  # noqa: BLE001 - stage record is supplemental here
                        pass

                completed_names = {
                    c["name"] for c in raw_checks if c["name"] and not c["skipped"]
                }
                expected_set = set(expected_checks)
                completed_count = (
                    len(completed_names & expected_set)
                    if expected_set
                    else len(completed_names)
                )
                runs.append(
                    {
                        "run_id": run_id,
                        "run_url": run_url,
                        "created_at": str(art.get("created_at") or ""),
                        "version_ref": str(entry.get("version_ref") or "unknown"),
                        "status": str(entry.get("status") or "unknown"),
                        "summary": str(entry.get("summary") or "")[:240],
                        "duration_seconds": entry.get("duration_seconds"),
                        "completed_checks": completed_count,
                        "expected_checks": len(expected_checks),
                        "checks": raw_checks,
                        "oracle_summaries": oracle_summaries,
                        "stage_record_verdict": stage_record_status,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"artifact {art.get('id')}: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"scheduled-audit-results listing failed: {type(exc).__name__}: {exc}"
        )

    fallback_audit_runs: list[dict[str, Any]] = []
    if not runs:
        try:
            wf_runs = fetch_github_json(
                f"/repos/{infra2_repo}/actions/workflows/ops-checks.yml/runs?per_page=25",
                token=token,
                opener=opener,
            )
            candidates = [
                r
                for r in (wf_runs.get("workflow_runs") or ())
                if r.get("event") in ("schedule", "workflow_dispatch")
                and (
                    r.get("event") == "workflow_dispatch"
                    or ":2" in str(r.get("created_at") or "")
                    or "T02:" in str(r.get("created_at") or "")
                )
            ][:5]
            for cand in candidates:
                rid = str(cand.get("id") or "")
                jobs_data = fetch_github_json(
                    f"/repos/{infra2_repo}/actions/runs/{rid}/jobs",
                    token=token,
                    opener=opener,
                )
                audit_job = next(
                    (
                        j
                        for j in (jobs_data.get("jobs") or ())
                        if j.get("name") == "Audit deploy dependency graph"
                        and j.get("conclusion") not in (None, "skipped")
                    ),
                    None,
                )
                if audit_job:
                    fallback_audit_runs.append(
                        {
                            "run_id": rid,
                            "run_url": str(cand.get("html_url") or ""),
                            "created_at": str(cand.get("created_at") or ""),
                            "conclusion": str(audit_job.get("conclusion") or "unknown"),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ops-checks fallback query failed: {type(exc).__name__}: {exc}")

    latest = runs[0] if runs else None
    completed = int(latest["completed_checks"]) if latest else 0
    expected = len(expected_checks)
    ratio = round(completed / expected, 4) if expected > 0 else 0.0
    return {
        "repo": infra2_repo,
        "expected_check_ids": list(expected_checks),
        "artifacts_count": len(runs),
        "latest_at_utc": latest["created_at"] if latest else None,
        "completeness": {
            "completed": completed,
            "expected": expected,
            "ratio": ratio,
        },
        "latest": latest,
        "runs": runs,
        "fallback_audit_runs": fallback_audit_runs,
        "errors": errors,
    }


def _latest_stage_record_for(
    infra2_repo: str,
    *,
    prefix: str,
    token: str,
    opener: HttpOpener,
) -> dict[str, Any] | None:
    try:
        wf = fetch_github_json(
            f"/repos/{infra2_repo}/actions/workflows/reconcile-iac-inputs.yml/runs?event=push&status=completed&per_page=8",
            token=token,
            opener=opener,
        )
        for run in wf.get("workflow_runs") or ():
            rid = str(run.get("id") or "")
            arts = fetch_github_json(
                f"/repos/{infra2_repo}/actions/runs/{rid}/artifacts",
                token=token,
                opener=opener,
            )
            for art in arts.get("artifacts") or ():
                if str(art.get("name") or "").startswith(prefix) and not art.get("expired"):
                    files = download_artifact_files(
                        str(art["archive_download_url"]), token=token, opener=opener
                    )
                    first = next(iter(files.values()), None)
                    if first:
                        rec = json.loads(first.decode("utf-8"))
                        return {
                            "artifact_name": str(art["name"]),
                            "env": str(rec.get("env") or ""),
                            "subject": str(rec.get("subject") or ""),
                            "verdict": str(rec.get("verdict") or ""),
                            "finished_at": str(rec.get("finished_at") or ""),
                            "run_url": str(rec.get("run_url") or ""),
                        }
    except Exception:  # noqa: BLE001
        return None
    return None


def compute_freshness(
    *,
    now: datetime,
    ci_post: Mapping[str, Any],
    scheduled_audit: Mapping[str, Any],
    runtime_health: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute strict `FRESH` / `STALE_WARN` / `STALE_CRITICAL` verdict (never green while empty)."""
    critical_reasons: list[str] = []
    warn_reasons: list[str] = []

    comp = scheduled_audit.get("completeness") or {}
    completed = int(comp.get("completed") or 0)
    expected = int(comp.get("expected") or 0)
    audit_count = int(scheduled_audit.get("artifacts_count") or 0)
    audit_dt = parse_iso_utc(scheduled_audit.get("latest_at_utc"))
    audit_age_hours = (
        round((now - audit_dt).total_seconds() / 3600.0, 2) if audit_dt else None
    )

    if expected <= 0:
        critical_reasons.append("No scheduled_audit checks declared in manifest (0 expected)")
    if audit_count <= 0:
        critical_reasons.append("No scheduled-audit-results artifacts available")
    elif completed <= 0:
        critical_reasons.append(f"Latest scheduled_audit completed 0/{expected} checks")
    elif completed < expected:
        warn_reasons.append(f"Partial scheduled_audit completeness: {completed}/{expected}")

    if audit_dt is None and audit_count > 0:
        critical_reasons.append("Latest scheduled_audit timestamp is unparseable")
    elif audit_age_hours is not None:
        if audit_age_hours > CRITICAL_AUDIT_AGE_HOURS:
            critical_reasons.append(
                f"Latest scheduled_audit is {audit_age_hours:.1f}h old (> {CRITICAL_AUDIT_AGE_HOURS:.0f}h)"
            )
        elif audit_age_hours > WARN_AUDIT_AGE_HOURS:
            warn_reasons.append(
                f"Latest scheduled_audit is {audit_age_hours:.1f}h old (> {WARN_AUDIT_AGE_HOURS:.0f}h)"
            )

    latest_audit = scheduled_audit.get("latest") or {}
    if latest_audit and latest_audit.get("status") != "pass":
        warn_reasons.append(
            f"Latest scheduled_audit status is {latest_audit.get('status')!r}"
        )

    ci_count = int(ci_post.get("artifacts_count") or 0)
    ci_dt = parse_iso_utc(ci_post.get("latest_at_utc"))
    ci_age_hours = (
        round((now - ci_dt).total_seconds() / 3600.0, 2) if ci_dt else None
    )
    if ci_count <= 0:
        warn_reasons.append("No ci-post-telemetry artifacts available yet")
    elif ci_age_hours is not None:
        if ci_age_hours > CRITICAL_CI_AGE_HOURS:
            critical_reasons.append(
                f"Latest ci.post telemetry is {ci_age_hours:.1f}h old (> {CRITICAL_CI_AGE_HOURS:.0f}h)"
            )
        elif ci_age_hours > WARN_CI_AGE_HOURS:
            warn_reasons.append(
                f"Latest ci.post telemetry is {ci_age_hours:.1f}h old (> {WARN_CI_AGE_HOURS:.0f}h)"
            )

    staging_health = runtime_health.get("staging") or {}
    prod_health = runtime_health.get("production") or {}
    staging_ok = staging_health.get("reachable") and staging_health.get("status") == "healthy"
    prod_ok = prod_health.get("reachable") and prod_health.get("status") == "healthy"
    if not staging_health.get("reachable") and not prod_health.get("reachable"):
        critical_reasons.append("Both Staging and Production /api/health?full=1 probes failed")
    else:
        if not staging_ok:
            warn_reasons.append(
                f"Staging health is {staging_health.get('status', 'unknown')}"
            )
        if not prod_ok:
            warn_reasons.append(
                f"Production health is {prod_health.get('status', 'unknown')}"
            )

    if critical_reasons:
        status = "STALE_CRITICAL"
    elif warn_reasons:
        status = "STALE_WARN"
    else:
        status = "FRESH"

    return {
        "status": status,
        "reasons": [*critical_reasons, *warn_reasons],
        "audit_age_hours": audit_age_hours,
        "ci_age_hours": ci_age_hours,
        "completeness": {"completed": completed, "expected": expected},
    }


def build_dashboard_data(
    *,
    repo_root: Path = REPO_ROOT,
    finance_repo: str = DEFAULT_FINANCE_REPO,
    infra2_repo: str = DEFAULT_INFRA2_REPO,
    staging_health_url: str = DEFAULT_STAGING_HEALTH_URL,
    prod_health_url: str = DEFAULT_PROD_HEALTH_URL,
    finance_token: str = "",
    infra2_token: str = "",
    opener: HttpOpener = default_opener,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect live dashboard JSON payload from all quality and runtime sources."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    manifest_path = repo_root / "runtime-hooks.manifest.json"
    ssot_path = repo_root / "common" / "meta" / "flows" / "user_cases_ssot.json"

    expected_checks = expected_scheduled_audit_checks(manifest_path)
    user_cases = collect_user_cases(ssot_path)
    ci_post = collect_ci_post(finance_repo, token=finance_token, opener=opener)
    scheduled_audit = collect_scheduled_audit(
        infra2_repo,
        expected_checks=expected_checks,
        token=infra2_token or finance_token,
        opener=opener,
    )
    runtime_health = {
        "staging": probe_runtime_health(
            staging_health_url, label="staging", opener=opener
        ),
        "production": probe_runtime_health(
            prod_health_url, label="production", opener=opener
        ),
    }
    stage_records = {
        "staging": _latest_stage_record_for(
            infra2_repo,
            prefix="stage-staging.release_validation-post-",
            token=infra2_token or finance_token,
            opener=opener,
        ),
        "production": _latest_stage_record_for(
            infra2_repo,
            prefix="stage-prod.release_integrity-post-",
            token=infra2_token or finance_token,
            opener=opener,
        ),
    }
    freshness = compute_freshness(
        now=current,
        ci_post=ci_post,
        scheduled_audit=scheduled_audit,
        runtime_health=runtime_health,
    )
    return {
        "schema_version": 1,
        "generated_at_utc": format_utc(current),
        "generated_at_utc8": format_utc8(current),
        "freshness": freshness,
        "runtime_health": runtime_health,
        "stage_records": stage_records,
        "scheduled_audit": scheduled_audit,
        "ci_post": ci_post,
        "user_cases": user_cases,
    }


def _svg_sparkline(values: Sequence[float | None], *, stroke: str, unit: str = "") -> str:
    clean = [float(v) for v in reversed(values) if v is not None]
    if len(clean) < 2:
        return "<span class=\"muted\">Insufficient trend points</span>"
    w, h, pad = 220, 44, 6
    lo, hi = min(clean), max(clean)
    span = hi - lo or 1.0
    pts = []
    for idx, val in enumerate(clean):
        x = pad + (w - 2 * pad) * (idx / (len(clean) - 1))
        y = h - pad - ((val - lo) / span) * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    latest_text = html.escape(f"{clean[-1]:.1f}{unit}")
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" aria-label="Trend ending {latest_text}">'
        f'<polyline fill="none" stroke="{html.escape(stroke)}" stroke-width="2" '
        f'points="{" ".join(pts)}" /></svg>'
    )


def _badge(label: str, kind: str) -> str:
    cls = {
        "ok": "badge-ok",
        "warn": "badge-warn",
        "bad": "badge-bad",
    }.get(kind, "badge-muted")
    return f'<span class="badge {cls}">{html.escape(label)}</span>'


def _health_card(env_data: Mapping[str, Any]) -> str:
    env_name = html.escape(str(env_data.get("env") or "").upper())
    status = str(env_data.get("status") or "error")
    version = html.escape(str(env_data.get("version") or "unknown"))
    latency = env_data.get("latency_ms")
    badge_kind = "ok" if status == "healthy" else ("warn" if status == "degraded" else "bad")
    rows = []
    for cname, cinfo in sorted((env_data.get("checks") or {}).items()):
        cstatus = str(cinfo.get("status") or "unknown")
        ckind = "ok" if cstatus == "present" else "bad"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(cname)}</code></td>"
            f"<td>{_badge(cstatus, ckind)}</td>"
            f"<td>{html.escape(str(cinfo.get('detail') or ''))}</td>"
            f"<td class=\"num\">{cinfo.get('duration_ms', 0):.1f} ms</td>"
            "</tr>"
        )
    if env_data.get("error"):
        err_html = f'<p class="err">{html.escape(str(env_data["error"]))}</p>'
    else:
        err_html = ""
    table_html = (
        "<table><thead><tr><th>Dependency</th><th>Status</th><th>Detail</th><th>Latency</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        if rows
        else '<p class="muted">No dependency checks returned.</p>'
    )
    lat_str = f"{latency:.1f} ms" if isinstance(latency, (int, float)) else "n/a"
    return (
        '<div class="card">'
        f'<div class="card-head"><h3>{env_name} · <code>{version}</code></h3>'
        f'<div>{_badge(status, badge_kind)} <span class="muted">{lat_str}</span></div></div>'
        f"{err_html}{table_html}</div>"
    )


def render_html(data: Mapping[str, Any]) -> str:
    """Render a standalone HTML dashboard with explicit freshness banner and XSS escaping."""
    fresh = data.get("freshness") or {}
    f_status = str(fresh.get("status") or "STALE_CRITICAL")
    banner_cls = {
        "FRESH": "banner-fresh",
        "STALE_WARN": "banner-warn",
        "STALE_CRITICAL": "banner-critical",
    }.get(f_status, "banner-critical")
    comp = (data.get("scheduled_audit") or {}).get("completeness") or {}
    comp_text = f"{int(comp.get('completed') or 0)}/{int(comp.get('expected') or 0)}"
    reasons = [f"<li>{html.escape(str(r))}</li>" for r in (fresh.get("reasons") or ())]
    reasons_html = f"<ul>{''.join(reasons)}</ul>" if reasons else "<p>All nightly and CI signals fresh.</p>"

    runtime = data.get("runtime_health") or {}
    health_html = _health_card(runtime.get("staging") or {}) + _health_card(
        runtime.get("production") or {}
    )

    audit = data.get("scheduled_audit") or {}
    audit_rows = []
    for run in audit.get("runs") or ():
        checks = run.get("checks") or []
        checks_badges = " ".join(
            _badge(
                c["name"],
                "warn" if c.get("skipped") else ("ok" if c.get("ok") else "bad"),
            )
            for c in checks
        )
        run_link = html.escape(str(run.get("run_url") or "#"))
        rid = html.escape(str(run.get("run_id") or "?"))
        st = str(run.get("status") or "unknown")
        st_kind = "ok" if st == "pass" else "bad"
        oracle_text = html.escape(
            json.dumps(run.get("oracle_summaries") or {}, sort_keys=True)
        )
        audit_rows.append(
            "<tr>"
            f'<td><a href="{run_link}">{rid}</a></td>'
            f"<td>{html.escape(str(run.get('created_at') or ''))}</td>"
            f"<td><code>{html.escape(str(run.get('version_ref') or ''))}</code></td>"
            f"<td>{_badge(st, st_kind)}</td>"
            f"<td>{int(run.get('completed_checks') or 0)}/{int(run.get('expected_checks') or 0)}</td>"
            f"<td>{checks_badges or '<span class=\"muted\">none</span>'}</td>"
            f"<td class=\"mono\">{oracle_text[:180]}</td>"
            "</tr>"
        )
    if not audit_rows and audit.get("fallback_audit_runs"):
        for fb in audit["fallback_audit_runs"]:
            rlink = html.escape(str(fb.get("run_url") or "#"))
            rid = html.escape(str(fb.get("run_id") or "?"))
            concl = str(fb.get("conclusion") or "unknown")
            audit_rows.append(
                "<tr>"
                f'<td><a href="{rlink}">{rid}</a></td>'
                f"<td>{html.escape(str(fb.get('created_at') or ''))}</td>"
                "<td><code>main</code></td>"
                f"<td>{_badge(concl, 'ok' if concl == 'success' else 'bad')}</td>"
                f"<td>0/{int(comp.get('expected') or 0)}</td>"
                '<td colspan="2" class="muted">Pre-Phase-2A ops-checks run (no scheduled-audit-results artifact yet)</td>'
                "</tr>"
            )

    ci_post = data.get("ci_post") or {}
    ci_runs = ci_post.get("runs") or []
    be_vals = [
        (r.get("backend") or {}).get("percent_covered") for r in ci_runs
    ]
    fe_vals = [
        (r.get("frontend") or {}).get("lines_pct") for r in ci_runs
    ]
    dur_vals = [r.get("execution_seconds") for r in ci_runs]

    ci_rows = []
    for r in ci_runs:
        rurl = html.escape(str(r.get("run_url") or "#"))
        sha = html.escape(str(r.get("sha") or ""))
        be = (r.get("backend") or {}).get("percent_covered")
        fe = (r.get("frontend") or {}).get("lines_pct")
        ex_s = r.get("execution_seconds")
        bu_s = r.get("budget_seconds")
        st = str(r.get("budget_state") or "n/a")
        st_kind = "ok" if st == "within" else ("warn" if st == "OVER" else "muted")
        ci_rows.append(
            "<tr>"
            f'<td><a href="{rurl}"><code>{sha}</code></a></td>'
            f"<td>{html.escape(str(r.get('generated_at_utc') or ''))}</td>"
            f"<td class=\"num\">{f'{ex_s}s / {bu_s}s' if ex_s is not None and bu_s else 'n/a'}</td>"
            f"<td>{_badge(st, st_kind)}</td>"
            f"<td class=\"num\">{f'{be:.2f}%' if isinstance(be, (int, float)) else 'n/a'}</td>"
            f"<td class=\"num\">{f'{fe:.2f}%' if isinstance(fe, (int, float)) else 'n/a'}</td>"
            "</tr>"
        )

    uc = data.get("user_cases") or {}
    uc_rows = []
    for dom in uc.get("domains") or ():
        uc_rows.append(
            "<tr>"
            f"<td>{html.escape(str(dom.get('id') or ''))}. {html.escape(str(dom.get('name') or ''))}</td>"
            f"<td class=\"num\">{int(dom.get('total') or 0)}</td>"
            f"<td class=\"num\">{int(dom.get('complete') or 0)}</td>"
            f"<td class=\"num\">{int(dom.get('partial') or 0)}</td>"
            f"<td class=\"num\">{int(dom.get('e2e_linked') or 0)}</td>"
            f"<td class=\"num\">{int(dom.get('benchmark_linked') or 0)}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Finance Report — Live Quality Board</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, -apple-system, sans-serif; }}
    body {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; line-height: 1.45; }}
    .banner {{ padding: 1rem 1.25rem; border-radius: 10px; margin-bottom: 1.25rem; border: 1px solid transparent; }}
    .banner-fresh {{ background: #dcfce7; border-color: #16a34a; color: #14532d; }}
    .banner-warn {{ background: #fef3c7; border-color: #d97706; color: #78350f; }}
    .banner-critical {{ background: #fee2e2; border-color: #dc2626; color: #7f1d1d; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; margin-bottom: 1.25rem; }}
    .card {{ border: 1px solid #cbd5e1; border-radius: 10px; padding: 1rem; }}
    .card-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; gap: 0.5rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; margin-bottom: 1rem; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }}
    th {{ font-weight: 600; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .badge {{ display: inline-block; padding: 0.15rem 0.45rem; border-radius: 999px; font-size: 0.78rem; font-weight: 600; margin: 1px; }}
    .badge-ok {{ background: #dcfce7; color: #166534; }}
    .badge-warn {{ background: #fef3c7; color: #92400e; }}
    .badge-bad {{ background: #fee2e2; color: #991b1b; }}
    .badge-muted {{ background: #e2e8f0; color: #334155; }}
    .muted {{ opacity: 0.75; font-size: 0.85rem; }}
    .err {{ color: #b91c1c; font-weight: 600; }}
    .mono {{ font-family: ui-monospace, monospace; font-size: 0.8rem; word-break: break-word; }}
    .spark {{ width: 220px; height: 44px; display: block; }}
  </style>
</head>
<body>
  <header>
    <h1>Finance Report — Live Quality Board</h1>
    <p class="muted">Machine data: <a href="./data.json"><code>data.json</code></a> · Back to <a href="../">docs</a></p>
  </header>

  <section class="banner {banner_cls}" data-freshness="{html.escape(f_status)}">
    <div class="card-head">
      <strong>Freshness Heartbeat: {html.escape(f_status)}</strong>
      <span>Nightly Completeness: <strong>{html.escape(comp_text)}</strong></span>
    </div>
    <div>Last updated: <strong>{html.escape(str(data.get('generated_at_utc8') or ''))}</strong> (<code>{html.escape(str(data.get('generated_at_utc') or ''))}</code>)</div>
    {reasons_html}
  </section>

  <h2>1. Runtime Dependencies (/api/health?full=1)</h2>
  <section class="grid">{health_html}</section>

  <h2>2. Nightly scheduled_audit &amp; Oracle Verdicts</h2>
  <table>
    <thead><tr><th>Run</th><th>Created (UTC)</th><th>Version</th><th>Status</th><th>Complete</th><th>Checks</th><th>Oracle Summary</th></tr></thead>
    <tbody>{''.join(audit_rows) or '<tr><td colspan="7" class="muted">No scheduled_audit runs observed.</td></tr>'}</tbody>
  </table>

  <h2>3. CI Timing &amp; Coverage Trends (ci.post)</h2>
  <section class="grid">
    <div class="card"><h3>Execution Window (s)</h3>{_svg_sparkline(dur_vals, stroke="#2563eb", unit="s")}</div>
    <div class="card"><h3>Backend Coverage (%)</h3>{_svg_sparkline(be_vals, stroke="#16a34a", unit="%")}</div>
    <div class="card"><h3>Frontend Lines (%)</h3>{_svg_sparkline(fe_vals, stroke="#7c3aed", unit="%")}</div>
  </section>
  <table>
    <thead><tr><th>SHA</th><th>Timestamp (UTC)</th><th>Execution / Budget</th><th>Budget</th><th>Backend</th><th>Frontend Lines</th></tr></thead>
    <tbody>{''.join(ci_rows) or '<tr><td colspan="6" class="muted">No ci-post-telemetry artifacts observed yet.</td></tr>'}</tbody>
  </table>

  <h2>4. User Cases SSOT ({int(uc.get('total') or 0)} total)</h2>
  <table>
    <thead><tr><th>Domain</th><th>Total</th><th>Complete</th><th>Partial</th><th>E2E Linked</th><th>Benchmark Linked</th></tr></thead>
    <tbody>{''.join(uc_rows)}</tbody>
  </table>
</body>
</html>
"""


def write_dashboard(
    *,
    output_dir: Path,
    repo_root: Path = REPO_ROOT,
    finance_repo: str = DEFAULT_FINANCE_REPO,
    infra2_repo: str = DEFAULT_INFRA2_REPO,
    staging_health_url: str = DEFAULT_STAGING_HEALTH_URL,
    prod_health_url: str = DEFAULT_PROD_HEALTH_URL,
    finance_token: str = "",
    infra2_token: str = "",
    opener: HttpOpener = default_opener,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate and write `data.json` and `index.html` into `output_dir`."""
    data = build_dashboard_data(
        repo_root=repo_root,
        finance_repo=finance_repo,
        infra2_repo=infra2_repo,
        staging_health_url=staging_health_url,
        prod_health_url=prod_health_url,
        finance_token=finance_token,
        infra2_token=infra2_token,
        opener=opener,
        now=now,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "index.html").write_text(render_html(data), encoding="utf-8")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the live freshness-tracked quality dashboard"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--finance-repo", default=DEFAULT_FINANCE_REPO)
    parser.add_argument("--infra2-repo", default=DEFAULT_INFRA2_REPO)
    parser.add_argument("--staging-health-url", default=DEFAULT_STAGING_HEALTH_URL)
    parser.add_argument("--prod-health-url", default=DEFAULT_PROD_HEALTH_URL)
    args = parser.parse_args(argv)

    finance_token = (
        os.environ.get("GITHUB_TOKEN", "").strip()
        or os.environ.get("GH_TOKEN", "").strip()
    )
    infra2_token = os.environ.get("INFRA2_TOKEN", "").strip() or finance_token
    data = write_dashboard(
        output_dir=args.output_dir,
        repo_root=args.repo_root.resolve(),
        finance_repo=args.finance_repo,
        infra2_repo=args.infra2_repo,
        staging_health_url=args.staging_health_url,
        prod_health_url=args.prod_health_url,
        finance_token=finance_token,
        infra2_token=infra2_token,
    )
    fresh = data["freshness"]
    print(
        f"Wrote quality dashboard to {args.output_dir} "
        f"(freshness={fresh['status']}, completeness={fresh['completeness']['completed']}/{fresh['completeness']['expected']})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
