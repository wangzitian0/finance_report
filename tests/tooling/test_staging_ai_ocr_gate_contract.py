"""Tests for the staging AI/OCR replay contract tool."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from tools import staging_ai_ocr_gate_contract as contract

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_49_gate_files_include_matrix_llm_proofs_and_supplementals(
    monkeypatch,
) -> None:
    """AC8.13.49: Gate file list is generated from one replay contract source."""
    monkeypatch.setattr(
        contract,
        "_load_matrix",
        lambda: {
            "proofs": [
                {
                    "file": "tests/e2e/test_statement_full_journey.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["llm"],
                },
                {
                    "file": "tests/e2e/test_not_llm.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["e2e"],
                },
                {
                    "file": "tests/e2e/test_wrong_tier.py",
                    "ci_tier": "pr",
                    "required_markers": ["llm"],
                },
            ]
        },
    )

    assert contract.gate_files() == [
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_statement_upload_e2e.py",
    ]


def test_AC8_13_49_missing_replay_counter_fails_closed(monkeypatch) -> None:
    """AC8.13.49: Every gate file must have explicit expected replay counters."""
    monkeypatch.setattr(
        contract,
        "_load_matrix",
        lambda: {
            "proofs": [
                {
                    "file": "tests/e2e/test_missing_counter.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["llm"],
                },
            ]
        },
    )

    with pytest.raises(SystemExit, match="Missing staging AI/OCR replay counters"):
        contract.gate_files()


def test_AC8_13_49_totals_and_shell_output_are_deterministic(monkeypatch) -> None:
    """AC8.13.49: Replay count totals and shell assignments share one source."""
    monkeypatch.setattr(
        contract,
        "gate_files",
        lambda: [
            "tests/e2e/test_statement_full_journey.py",
            "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        ],
    )

    assert contract.totals(contract.gate_files()) == {
        "uploads": 3,
        "parse_completions": 3,
        "brokerage_imports": 2,
        "report_verifications": 0,
    }
    shell = contract.emit_shell()
    assert (
        "STAGING_AI_OCR_TESTS=(tests/e2e/test_statement_full_journey.py "
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py)"
    ) in shell
    assert "STAGING_AI_OCR_EXPECTED_UPLOADS=3" in shell
    assert "STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS=3" in shell
    assert "STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS=2" in shell
    assert "STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS=0" in shell


def test_AC8_13_49_main_supports_shell_and_human_output(monkeypatch, capsys) -> None:
    """AC8.13.49: CLI output supports workflow shell eval and human inspection."""
    monkeypatch.setattr(
        contract,
        "gate_files",
        lambda: ["tests/e2e/test_statement_full_journey.py"],
    )

    monkeypatch.setattr(sys, "argv", ["staging_ai_ocr_gate_contract.py", "--shell"])
    assert contract.main() == 0
    assert "STAGING_AI_OCR_EXPECTED_UPLOADS=1" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["staging_ai_ocr_gate_contract.py"])
    assert contract.main() == 0
    output = capsys.readouterr().out
    assert "Staging AI/OCR gate files:" in output
    assert "- tests/e2e/test_statement_full_journey.py" in output
    assert "- uploads: 1" in output


CANARY_FILE = "tests/e2e/test_brokerage_upload_to_portfolio_value.py"

HEAVY_AUDIT_JOURNEYS = (
    "tests/e2e/test_statement_full_journey.py",
    "tests/e2e/test_four_asset_net_worth_golden_path.py",
    "tests/e2e/test_personal_financial_report_package.py",
)


def test_AC8_13_156_canary_corpus_is_minimal_liveness() -> None:
    """AC-testing.deploy-gates.31: AC8.13.156: The blocking canary is one minimal upload/parse/import liveness
    check that makes no broad audit assertions."""
    canary = contract.canary_files()

    # Exactly one representative liveness journey — the brokerage upload→parse→
    # import→value path is the only single test that exercises `import`.
    assert canary == [CANARY_FILE]

    # The canary is a subset of the full derived llm post-merge corpus and every
    # canary file is fail-closed against the replay-counter source.
    assert set(canary) <= set(contract.gate_files())
    assert all(path in contract.REPLAY_COUNTERS for path in canary)

    # No broad audit assertions: the canary verifies liveness, not report output.
    assert contract.totals(canary)["report_verifications"] == 0

    # The selectable corpus shell honors the canary selection.
    shell = contract.emit_shell(contract.canary_files())
    assert f"STAGING_AI_OCR_TESTS=({CANARY_FILE})" in shell


def test_AC8_13_159_blocking_path_excludes_heavy_audit_journeys() -> None:
    """AC-testing.deploy-gates.34: AC8.13.159: heavy audit journeys live only in the audit-replay corpus and
    cannot creep into the blocking canary path."""
    canary = set(contract.canary_files())
    audit_replay = set(contract.audit_replay_files())

    # The two corpora partition the full derived corpus with no overlap.
    assert canary & audit_replay == set()
    assert canary | audit_replay == set(contract.gate_files())

    # Every heavy audit journey is in audit-replay, never in the blocking canary.
    for heavy in HEAVY_AUDIT_JOURNEYS:
        assert heavy in audit_replay
        assert heavy not in canary

    # A hypothetical newly-added llm post-merge proof defaults to audit-replay
    # (subtraction), so a new heavy journey can never silently block production.
    import tools.staging_ai_ocr_gate_contract as live

    # Use a genuinely NEW path (absent from both the real gate corpus and the
    # canary list) so the subtraction is actually exercised — unioning in an
    # existing CANARY_FILE would be a no-op and assert nothing.
    new_heavy = "tests/e2e/test_hypothetical_new_heavy_proof.py"
    assert new_heavy not in set(live.gate_files())
    assert new_heavy not in set(live.canary_files())

    original_gate_files = live.gate_files
    try:
        live.gate_files = lambda: sorted(  # type: ignore[assignment]
            set(original_gate_files()) | {new_heavy}
        )
        # Derived by subtraction (gate_files - canary), so the brand-new heavy
        # file lands in audit-replay and never in the blocking canary.
        assert new_heavy in set(live.audit_replay_files())
        assert new_heavy not in set(live.canary_files())
    finally:
        live.gate_files = original_gate_files  # type: ignore[assignment]


def test_AC8_13_109_ai_ocr_gate_tests_use_isolated_users() -> None:
    """AC-testing.deploy-gates.23: AC8.13.109: Post-merge AI/OCR gate tests must not share mutable users."""
    shared_user_fixtures = {"authenticated_page", "shared_auth_state"}

    offenders: list[str] = []
    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            used_fixtures = {arg.arg for arg in node.args.args}
            shared = sorted(used_fixtures & shared_user_fixtures)
            if shared:
                offenders.append(
                    f"{relative_path}::{node.name} uses {', '.join(shared)}"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_tests_use_cookie_auth_for_api_calls() -> None:
    """AC8.13.109: Provider-backed E2E API calls must use HttpOnly cookie auth."""
    offenders: list[str] = []
    forbidden_snippets = [
        "localStorage.getItem('finance_access_token')",
        'localStorage.getItem("finance_access_token")',
        '"Authorization": f"Bearer {access_token}"',
        "'Authorization': f'Bearer {access_token}'",
    ]

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                offenders.append(f"{relative_path} contains {snippet}")

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_tests_avoid_networkidle_waits() -> None:
    """AC8.13.109: Deployed browser gates wait on explicit UI, not networkidle."""
    offenders: list[str] = []

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        if "networkidle" in source:
            offenders.append(f"{relative_path} waits for networkidle")

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_httpx_calls_use_absolute_api_urls() -> None:
    """AC8.13.109: Httpx-backed deployed E2E calls must not use relative URLs."""
    offenders: list[str] = []
    relative_prefixes = ("/api/", "/assets/")

    def relative_url_prefix(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr) and node.values:
            first_value = node.values[0]
            if isinstance(first_value, ast.Constant) and isinstance(
                first_value.value, str
            ):
                return first_value.value
        return None

    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            url_prefix = relative_url_prefix(first_arg)
            if url_prefix and url_prefix.startswith(relative_prefixes):
                offenders.append(
                    f"{relative_path}:{node.lineno} uses relative API URL {url_prefix!r}"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_dashboard_analytics_locator_is_exact() -> None:
    """AC8.13.109: Dashboard checks must not also match loading status labels."""
    offenders: list[str] = []

    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get_by_label":
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            exact_keyword = next(
                (kw for kw in node.keywords if kw.arg == "exact"),
                None,
            )
            is_dashboard_analytics = (
                isinstance(first_arg, ast.Constant)
                and first_arg.value == "Dashboard analytics"
            )
            is_exact = (
                exact_keyword is not None
                and isinstance(exact_keyword.value, ast.Constant)
                and exact_keyword.value.value is True
            )
            if is_dashboard_analytics and not is_exact:
                offenders.append(
                    f"{relative_path}:{node.lineno} uses inexact Dashboard analytics label"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_does_not_assert_hidden_statement_overlay_links() -> (
    None
):
    """AC8.13.109: Statement list checks use visible text/API state, not overlay links."""
    offenders: list[str] = []
    forbidden_snippets = [
        'locator("a").filter(has_text=',
        "locator('a').filter(has_text=",
        "locator(f'a[href=",
        'locator(f"a[href=',
    ]

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                offenders.append(f"{relative_path} contains {snippet}")

    assert offenders == []


_JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="staging-ai-ocr" tests="3" failures="1" errors="0" skipped="1">
    <testcase classname="tests.e2e.test_a" name="test_upload_ok"/>
    <testcase classname="tests.e2e.test_b" name="test_parse_cmb">
      <failure message="parse failed">Date is required</failure>
    </testcase>
    <testcase classname="tests.e2e.test_c" name="test_skipme"><skipped/></testcase>
  </testsuite>
</testsuites>
"""


def test_AC8_13_137_summarize_junit_reports_per_doc_failures(tmp_path: Path) -> None:
    """AC-testing.deploy-gates.28: AC8.13.137: the gate summarizes JUnit results into real pass/fail counts and
    names the failing corpus docs, instead of a binary "Failures observed: 1+"."""
    xml = tmp_path / "gate.xml"
    xml.write_text(_JUNIT_XML, encoding="utf-8")

    summary = contract.summarize_junit([xml])

    assert summary["total"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["failed_tests"] == ["tests.e2e.test_b::test_parse_cmb"]


def test_AC8_13_137_render_junit_summary_lists_failed_tests(tmp_path: Path) -> None:
    """AC8.13.137: the rendered markdown names the failed test so the red gate is
    actionable (which doc failed), not opaque."""
    xml = tmp_path / "gate.xml"
    xml.write_text(_JUNIT_XML, encoding="utf-8")

    rendered = contract.render_junit_summary(contract.summarize_junit([xml]))

    assert "passed: 1" in rendered
    assert "failed: 1" in rendered
    assert "tests.e2e.test_b::test_parse_cmb" in rendered


def test_AC8_13_137_summarize_junit_tolerates_missing_xml(tmp_path: Path) -> None:
    """AC8.13.137: a missing/unreadable XML yields an empty summary, never a crash,
    so the gate's reporting step can't itself fail the workflow."""
    summary = contract.summarize_junit([tmp_path / "does-not-exist.xml"])
    assert summary == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failed_tests": [],
    }


# ── #1806: failure attribution, bounded transient retry, close-on-green ──────

_GATE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "staging-ai-ocr-gate.yml"


def _gate_run_script() -> str:
    import yaml

    doc = yaml.safe_load(_GATE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = doc["jobs"]["run"]["steps"]
    step = next(s for s in steps if s.get("id") == "staging_ai_ocr_tests")
    return step["run"]


def _junit(tmp_path: Path, name: str, *cases: str) -> Path:
    body = "\n".join(cases)
    xml = tmp_path / name
    xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite '
        f'name="staging-ai-ocr" tests="{len(cases)}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return xml


_TIMEOUT_CASE = (
    '<testcase classname="tests.e2e.test_statement_full_journey" name="test_parse">'
    '<failure message="statement 42 did not reach parsed within 480000ms; '
    'no poll payload was returned">timeout</failure></testcase>'
)
_FX_GAP_CASE = (
    '<testcase classname="tests.e2e.test_institution_statement_journeys" name="test_approve">'
    '<failure message="approve gate rejected statement 7: Missing FX rate for '
    'CNY/SGD on 2026-05-31">fx</failure></testcase>'
)
_ASSERTION_CASE = (
    '<testcase classname="tests.e2e.test_personal_financial_report_package" name="test_equity">'
    '<failure message="AssertionError: assert Decimal is wrong">boom</failure></testcase>'
)


class _FakeHealthResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeHealthResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_AC_testing_deploy_gates_37_preflight_reads_deployed_health_surface(
    monkeypatch,
) -> None:
    """AC-testing.deploy-gates.37: the preflight queries the deployed /api/health
    surface (manifest-required checks) and fails on any miss — it recomputes no
    environment state of its own (the #1435 lesson)."""
    import urllib.request

    seen: dict[str, str] = {}

    def _healthy_urlopen(url: str, timeout: float) -> _FakeHealthResponse:
        seen["url"] = url
        return _FakeHealthResponse(
            {"status": "healthy", "checks": {"database": True, "s3": True}}
        )

    monkeypatch.setattr(urllib.request, "urlopen", _healthy_urlopen)
    ok, reason = contract.preflight("https://staging.example")
    assert (ok, reason) == (True, "healthy")
    # ?full=1 is load-bearing: the default health form checks only database+S3;
    # full asserts the whole manifest-required dependency set for the tier.
    assert seen["url"] == "https://staging.example/api/health?full=1"

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout: _FakeHealthResponse(
            {"status": "healthy", "checks": {"database": True, "s3": False}}
        ),
    )
    ok, reason = contract.preflight("https://staging.example")
    assert not ok and reason == "required dependency checks failing: s3"

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout: _FakeHealthResponse({"status": "degraded", "checks": {}}),
    )
    ok, reason = contract.preflight("https://staging.example")
    assert not ok and reason.startswith("health status is 'degraded'")


def test_AC_testing_deploy_gates_37_gate_preflights_before_corpus_spend() -> None:
    """AC-testing.deploy-gates.37: the gate runs the preflight after the version
    check and before the corpus, and a preflight miss records the distinct
    precondition-failed status instead of a regression."""
    script = _gate_run_script()
    # .index raises ValueError when a marker is missing — existence and ordering
    # are proven together, with no text-mirror assertions.
    version_at = script.index("test_version_check.py")
    preflight_at = script.index("--preflight")
    precondition_record_at = script.index('"precondition-failed"')
    corpus_at = script.index('pytest "${STAGING_AI_OCR_TESTS[@]}"')
    assert version_at < preflight_at < precondition_record_at < corpus_at

    # The corpus checkout (deployed version) may predate the tool's --preflight
    # flag: argparse exits 2 on the unknown flag, and the gate must SKIP the
    # preflight then — only a real health miss (exit 1) may record the
    # precondition status. Otherwise every nightly between merging #1806 and
    # deploying the next release would spuriously alert precondition-failed.
    skip_guard_at = script.index("predates --preflight")
    assert preflight_at < skip_guard_at < precondition_record_at


def test_AC_testing_deploy_gates_38_transient_classification_precedence(
    tmp_path: Path,
) -> None:
    """AC-testing.deploy-gates.38: JUnit failures classify into regression |
    precondition | transient with regression-first precedence, so co-occurring
    noise can never mask a real regression; only transient failures yield
    retry targets."""
    transient_only = contract.classify_junit(
        [_junit(tmp_path, "transient.xml", _TIMEOUT_CASE)]
    )
    assert transient_only["status"] == "provider-transient"
    assert transient_only["retry_targets"] == [
        "tests/e2e/test_statement_full_journey.py"
    ]

    fx_gap = contract.classify_junit([_junit(tmp_path, "fx.xml", _FX_GAP_CASE)])
    assert (fx_gap["status"], fx_gap["retry_targets"]) == ("precondition-failed", [])

    mixed = contract.classify_junit(
        [_junit(tmp_path, "mixed.xml", _TIMEOUT_CASE, _FX_GAP_CASE, _ASSERTION_CASE)]
    )
    assert mixed["status"] == "regression-failed"
    assert len(mixed["by_class"]["transient"]) == 1
    assert len(mixed["by_class"]["precondition"]) == 1
    assert len(mixed["by_class"]["regression"]) == 1

    clean = contract.classify_junit([_junit(tmp_path, "clean.xml")])
    assert (clean["status"], clean["retry_targets"]) == ("passed", [])


def test_AC_testing_deploy_gates_38_gate_retries_transients_once_then_escalates(
    tmp_path: Path,
) -> None:
    """AC-testing.deploy-gates.38: the gate grants transient-only reds exactly one
    bounded retry of the affected files, and a reproduced transient with a
    standing open transient alert escalates to regression-failed."""
    script = _gate_run_script()
    classify_at = script.index("--classify-junit")
    retry_at = script.index("staging-ai-ocr-retry.xml")
    escalate_at = script.index(
        'AI_OCR_FAILURE_CLASS="regression-failed"\n', classify_at
    )
    record_at = script.index('record_and_finish "$gate_status" "$AI_OCR_FAILURE_CLASS"')
    assert classify_at < retry_at < record_at and retry_at < escalate_at < record_at

    shell = contract.emit_classification_shell(
        contract.classify_junit([_junit(tmp_path, "transient.xml", _TIMEOUT_CASE)])
    )
    assert shell.splitlines() == [
        "AI_OCR_FAILURE_CLASS=provider-transient",
        "AI_OCR_RETRY_TESTS=(tests/e2e/test_statement_full_journey.py)",
    ]

    # False-green guard: the shell adapter is only consumed on RED runs, so a
    # classification with no attributable cases (missing/unparseable JUnit)
    # must map to regression-failed — never let a red run publish "passed".
    empty_shell = contract.emit_classification_shell(
        contract.classify_junit([tmp_path / "does-not-exist.xml"])
    )
    assert empty_shell.splitlines() == [
        "AI_OCR_FAILURE_CLASS=regression-failed",
        "AI_OCR_RETRY_TESTS=()",
    ]

    # And the workflow only classifies when the JUnit file exists at all.
    # rindex bounded by the classify call finds the guard INSIDE the red
    # branch (write_staging_audit_result has an earlier, unrelated -f check).
    script = _gate_run_script()
    classify_at = script.index("--classify-junit")
    red_branch_at = script.index('if [ "$gate_status" -ne 0 ]')
    xml_guard_at = script.rindex(
        "-f test-results/staging-ai-ocr-gate.xml", 0, classify_at
    )
    assert red_branch_at < xml_guard_at < classify_at


def test_AC_testing_deploy_gates_39_alert_body_carries_machine_attribution(
    tmp_path: Path,
) -> None:
    """AC-testing.deploy-gates.39: the alert-issue body is generated from the
    JUnit attribution (per-class case lists), never a hardcoded parse-quality
    claim, and the workflow posts that generated body."""
    classification = contract.classify_junit(
        [_junit(tmp_path, "mixed.xml", _TIMEOUT_CASE, _ASSERTION_CASE)]
    )
    body = contract.render_alert_body(
        classification, run_id="99", expected_sha="v0.1.36", app_url="https://s"
    )
    body.index("tests.e2e.test_personal_financial_report_package::test_equity")
    body.index("tests.e2e.test_statement_full_journey::test_parse")
    assert body.index("regression") < body.index("transient")
    assert body.find("parse quality dropped") == -1

    # Existence only (no ordering): record_and_finish is defined before the
    # corpus section, so --body-file textually precedes --alert-body-out.
    script = _gate_run_script()
    script.index("--alert-body-out")
    script.index("--body-file")


def test_AC_testing_deploy_gates_40_green_run_closes_standing_alerts() -> None:
    """AC-testing.deploy-gates.40: a green gate run auto-closes every standing
    gate alert class (including gate-timeout), after the red path and before
    the passed status is recorded; per-class dedup of open alerts remains."""
    script = _gate_run_script()
    close_loop_at = script.index("for resolved_title in")
    close_at = script.index("Auto-closing")
    red_record_at = script.index(
        'record_and_finish "$gate_status" "$AI_OCR_FAILURE_CLASS"'
    )
    passed_at = script.index("ai_ocr_status=passed")
    assert red_record_at < close_loop_at < close_at < passed_at

    resolved_block = script[close_loop_at:close_at]
    for alert_class in (
        "regression-failed",
        "provider-transient",
        "precondition-failed",
        "version-check-failed",
        "gate produced no result",
    ):
        resolved_block.index(alert_class)

    # Dedup of open alerts is untouched (#1767): the create path still checks
    # for an existing open issue before filing a new one.
    script.index("not duplicating")


def test_AC_testing_deploy_gates_38_main_dispatches_classify_and_preflight(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """AC-testing.deploy-gates.38: the CLI dispatch paths the workflow evals
    (--classify-junit writing the alert body, --preflight) are exercised
    end-to-end, so the gate's shell contract cannot drift untested."""
    xml = _junit(tmp_path, "transient.xml", _TIMEOUT_CASE)
    body_out = tmp_path / "alert-body.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_ai_ocr_gate_contract.py",
            "--classify-junit",
            str(xml),
            "--alert-body-out",
            str(body_out),
            "--run-id",
            "7",
            "--expected-sha",
            "v9",
            "--app-url",
            "https://s",
        ],
    )
    assert contract.main() == 0
    out = capsys.readouterr().out
    out.index("AI_OCR_FAILURE_CLASS=provider-transient")
    body_out.read_text(encoding="utf-8").index("transient")

    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout: _FakeHealthResponse(
            {"status": "healthy", "checks": {"database": True}}
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["staging_ai_ocr_gate_contract.py", "--preflight", "--base-url", "https://s"],
    )
    assert contract.main() == 0

    monkeypatch.setattr(sys, "argv", ["staging_ai_ocr_gate_contract.py", "--preflight"])
    assert contract.main() == 2
