"""Direct api-wrapper call-site ratchet (#1868 S5 PR-C, G-fetch-ratchet)."""

from __future__ import annotations

import json

from common.testing import fe_fetch_ratchet


def _write_fe_source(directory, name: str, *, calls: list[str]) -> None:
    body = "\n".join(f"const x{i} = {call};" for i, call in enumerate(calls))
    (directory / name).write_text(body + "\n", encoding="utf-8")


def test_AC_testing_fe_fetch_1_ratchet_is_locked_and_only_goes_down(
    monkeypatch, tmp_path
) -> None:
    """AC-testing.fe-fetch.1: the committed baseline holds, growth fails, --update
    refuses to raise, and the counter is generic-aware (apiFetch<T>(...) counts too)."""
    assert fe_fetch_ratchet.main([]) == 0

    fake_src = tmp_path / "src"
    (fake_src / "components").mkdir(parents=True)
    (fake_src / "app").mkdir(parents=True)
    (fake_src / "components" / "__tests__").mkdir()

    _write_fe_source(
        fake_src / "components",
        "Widget.tsx",
        calls=['apiFetch("/api/a")', 'apiFetch<Foo>("/api/b")', 'apiStream("/api/c")'],
    )
    _write_fe_source(
        fake_src / "app",
        "page.tsx",
        calls=['apiDelete("/api/d")', 'apiUpload<Bar>("/api/e")'],
    )
    # Excluded: a test file and a __tests__ directory, even though both call apiFetch.
    _write_fe_source(
        fake_src / "components", "Widget.test.tsx", calls=['apiFetch("/api/a")']
    )
    _write_fe_source(
        fake_src / "components" / "__tests__", "helper.ts", calls=['apiFetch("/api/a")']
    )

    fake_baseline = tmp_path / "baseline.json"
    fake_baseline.write_text(json.dumps({"total": 0}), encoding="utf-8")
    monkeypatch.setattr(fe_fetch_ratchet, "FRONTEND_SRC", fake_src)
    monkeypatch.setattr(fe_fetch_ratchet, "BASELINE_PATH", fake_baseline)

    counts = fe_fetch_ratchet.count_call_sites()
    # 3 in Widget.tsx (incl. the generic apiFetch<Foo>) + 2 in page.tsx; test files excluded.
    assert sum(counts.values()) == 5
    counted_names = {key.rsplit("/", 1)[-1] for key in counts}
    assert counted_names == {"Widget.tsx", "page.tsx"}

    # Growth over the (zero) baseline is red; --update refuses to raise.
    assert fe_fetch_ratchet.main([]) == 1
    assert fe_fetch_ratchet.main(["--update"]) == 1
    assert json.loads(fake_baseline.read_text())["total"] == 0

    # Paydown may lower the baseline.
    fake_baseline.write_text(json.dumps({"total": 10}), encoding="utf-8")
    assert fe_fetch_ratchet.main(["--update"]) == 0
    assert json.loads(fake_baseline.read_text())["total"] == 5
