"""CODE / LLM authority classifier + per-package counter (EPIC-026 AC26.9).

Model (see common/authority/readme.md):
- Every AC is one bit, **detected from its test shape** (not declared):
    * ``LLM``  — the test exercises the record/replay (cassette) harness.
    * ``CODE`` — a structured-input deterministic test, no LLM in the loop.
- Every package (here: EPIC) gets an ``LLM-share`` = #LLM / (#CODE + #LLM), and
  falls into one of four bands:
    * ``CODE-ONLY`` (share == 0)     — enforceable: no LLM permitted
    * ``CODE-LED``  (0 < share < 50)
    * ``LLM-LED``   (50 <= share < 100)
    * ``LLM-ONLY``  (share == 100)   — enforceable: no hardcode permitted

This module is the base library; ``tools/authority_counter.py`` is the runnable
counter. Pure-Python, no key/network/DB — runs in the lint job.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

# Band names are the SINGLE authority vocabulary (common.authority.authority_matrix):
# the detected band scale IS the declared PackageTier scale — imported, not
# re-declared, so the two views cannot drift apart.
from common.authority.authority_matrix import PACKAGE_TIERS as BANDS

REPO_ROOT = Path(__file__).resolve().parents[2]
EPIC_DIR = REPO_ROOT / "docs" / "project"

# A test is an LLM test iff it drives the record/replay machinery.
LLM_TEST_MARKERS = (
    "cassette",
    "LLM_CASSETTE_MODE",
    "CassetteMode",
    "current_mode",
    "stream_ai_json",
    "litellm_stream",
)

CODE_ONLY, CODE_LED, LLM_LED, LLM_ONLY = BANDS

_AC_ROW = re.compile(r"\|\s*(AC\d+\.\d+\.\d+)\s*\|")
_FILE_TOKEN = re.compile(r"([\w./-]+\.(?:py|tsx|ts))")
# Skip vendored/duplicated trees: worktree copies and the `repo/` submodule each
# hold a FULL copy of the test tree, which would make every basename ambiguous.
_SKIP_DIRS = (
    "node_modules",
    "/.venv",
    "/.git/",
    "/dist/",
    "/build/",
    "/.claude/",
    "/repo/",
)


def band(llm_share: float) -> str:
    """Map an LLM-share percentage (0..100) to its band."""
    if llm_share <= 0:
        return CODE_ONLY
    if llm_share < 50:
        return CODE_LED
    if llm_share < 100:
        return LLM_LED
    return LLM_ONLY


def build_test_index(root: Path = REPO_ROOT) -> dict[str, list[Path]]:
    """Index test files by basename once (basename -> all paths with that name)."""
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        text = str(path)
        if any(skip in text for skip in _SKIP_DIRS):
            continue
        if path.suffix in (".py", ".tsx", ".ts") and path.is_file():
            index.setdefault(path.name, []).append(path)
    return index


def resolve_token(token: str, index: dict[str, list[Path]]) -> Path | None:
    """Resolve an EPIC-table file token to a real path.

    Disambiguates real basename collisions (e.g. two ``test_core_journeys.py``) by
    matching the token's directory suffix; if still ambiguous, returns None so the
    AC is counted ``unknown`` rather than silently mis-classified.
    """
    token = token.strip().strip("`")
    candidates = index.get(token.split("/")[-1], [])
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    suffix = token.lstrip("./")
    matches = [p for p in candidates if p.as_posix().endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def is_llm_test(
    path: Path | None, _cache: dict[Path, bool] | None = None
) -> bool | None:
    """True if the test file drives the cassette/replay harness, None if unreadable."""
    if path is None:
        return None
    if _cache is not None and path in _cache:
        return _cache[path]
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    verdict = any(marker in text for marker in LLM_TEST_MARKERS)
    if _cache is not None:
        _cache[path] = verdict
    return verdict


def classify_test_files(
    file_tokens: list[str], index: dict[str, list[Path]], cache: dict[Path, bool]
) -> str:
    """Classify one AC from its test-file tokens: 'LLM' | 'CODE' | 'unknown'."""
    verdict = "unknown"
    for token in file_tokens:
        path = resolve_token(token, index)
        llm = is_llm_test(path, cache)
        if llm is True:
            return "LLM"
        if llm is False:
            verdict = "CODE"
    return verdict


def iter_ac_rows(epic_dir: Path = EPIC_DIR) -> Iterator[tuple[str, str, list[str]]]:
    """Yield (epic, ac_id, [test-file tokens]) from every EPIC AC table row."""
    for epic_doc in sorted(epic_dir.glob("EPIC-*.md")):
        epic = epic_doc.stem.split(".")[0]
        for line in epic_doc.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = _AC_ROW.search(line)
            if not match:
                continue
            yield epic, match.group(1), _FILE_TOKEN.findall(line)


def classify_repo(root: Path = REPO_ROOT) -> dict:
    """Classify every AC and aggregate per EPIC + overall into bands."""
    index = build_test_index(root)
    cache: dict[Path, bool] = {}
    per_epic: dict[str, dict[str, int]] = {}
    for epic, _ac, tokens in iter_ac_rows(root / "docs" / "project"):
        bucket = per_epic.setdefault(
            epic, {"total": 0, "code": 0, "llm": 0, "unknown": 0}
        )
        verdict = classify_test_files(tokens, index, cache)
        bucket["total"] += 1
        bucket[verdict.lower()] += 1

    def finalize(b: dict[str, int]) -> dict:
        known = b["code"] + b["llm"]
        share = round(100 * b["llm"] / known, 1) if known else 0.0
        return {**b, "llm_share": share, "band": band(share)}

    packages = {epic: finalize(b) for epic, b in sorted(per_epic.items())}
    overall = {"total": 0, "code": 0, "llm": 0, "unknown": 0}
    for b in per_epic.values():
        for key in overall:
            overall[key] += b[key]
    return {"packages": packages, "overall": finalize(overall)}
