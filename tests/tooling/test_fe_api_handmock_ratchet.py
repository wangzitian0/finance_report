"""FE hand-mocked-vector-endpoint ratchet (issue #1827, G-contract-reddens).

The API response conformance vectors only close the contract-drift blind spot
for tests that actually LOAD them; this ratchet locks the count of frontend
test files that still hand-write JSON for a vectored endpoint to
decrease-only, so the conversion debt cannot silently grow back.
"""

from __future__ import annotations

import json

from common.testing import fe_api_handmock_ratchet


def _write_fe_test(
    directory, name: str, *, mocks_api: bool, marker: str, imports_fixture: bool
) -> None:
    parts = []
    if mocks_api:
        parts.append('vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }))')
    if imports_fixture:
        parts.append('import { balanceSheetVector } from "./fixtures/apiVectors"')
    parts.append(f'const marker = "{marker}"')
    (directory / name).write_text("\n".join(parts) + "\n", encoding="utf-8")


def test_AC_testing_fe_handmock_1_ratchet_is_locked_and_only_goes_down(
    monkeypatch, tmp_path
) -> None:
    """AC-testing.fe-handmock.1: the committed baseline holds, growth fails,
    --update refuses to raise, converted files (fixture importers) are exempt."""
    assert fe_api_handmock_ratchet.main([]) == 0

    # Synthetic frontend src tree: one hand-mocker, one converted file, one
    # unrelated test — only the hand-mocker counts.
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    _write_fe_test(
        fake_src,
        "a.test.tsx",
        mocks_api=True,
        marker="total_assets",
        imports_fixture=False,
    )
    _write_fe_test(
        fake_src,
        "b.test.tsx",
        mocks_api=True,
        marker="total_assets",
        imports_fixture=True,
    )
    _write_fe_test(
        fake_src,
        "c.test.ts",
        mocks_api=True,
        marker="unrelated_field",
        imports_fixture=False,
    )
    _write_fe_test(
        fake_src,
        "d.test.ts",
        mocks_api=False,
        marker="total_assets",
        imports_fixture=False,
    )

    fake_baseline = tmp_path / "baseline.json"
    fake_baseline.write_text(json.dumps({"total": 0}), encoding="utf-8")
    monkeypatch.setattr(fe_api_handmock_ratchet, "FRONTEND_SRC", fake_src)
    monkeypatch.setattr(fe_api_handmock_ratchet, "BASELINE_PATH", fake_baseline)

    counted = fe_api_handmock_ratchet.count_handmock_files()
    assert sum(counted.values()) == 1
    assert all(key.endswith("a.test.tsx") for key in counted)

    # Growth over the (zero) baseline is red; --update refuses to raise.
    assert fe_api_handmock_ratchet.main([]) == 1
    assert fe_api_handmock_ratchet.main(["--update"]) == 1
    assert json.loads(fake_baseline.read_text())["total"] == 0

    # Paydown may lower the baseline.
    fake_baseline.write_text(json.dumps({"total": 5}), encoding="utf-8")
    assert fe_api_handmock_ratchet.main(["--update"]) == 0
    assert json.loads(fake_baseline.read_text())["total"] == 1
