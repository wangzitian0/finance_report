"""AC-llm.banned-models.1: glm-4.6v is never used, in any file (owner rule, 2026-10-23, #2635).

One rule covers code, config, docs and tests. The only exemption is a provenance note in a
recorded cassette fixture: that file is data written by the recorder and says which engine
recorded it. Re-recording with the SDK multimodal model removes the note.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(r"glm-?4\.?6v", re.IGNORECASE)
RECORDED_DATA = "common/testing/fixtures/llm_cassettes/ground_truth/"
THIS_FILE = "tests/tooling/test_banned_models.py"
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".txt",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".example",
    ".ctmpl",
    ".hcl",
}


def _tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [
        p
        for p in out.split("\0")
        if p
        and (Path(p).suffix in TEXT_SUFFIXES or p.endswith(".env.example"))
        and p != THIS_FILE
    ]


def _hits() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for rel in _tracked_text_files():
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        numbers = [n for n, line in enumerate(lines, 1) if BANNED.search(line)]
        if numbers:
            found[rel] = numbers
    return found


def test_AC_llm_banned_models_1_no_tracked_file_names_glm_4_6v():
    hits = {p: n for p, n in _hits().items() if not p.startswith(RECORDED_DATA)}
    assert not hits, f"glm-4.6v is banned; remove it from: {hits}"


def test_AC_llm_banned_models_1_the_only_exemption_is_a_recorded_provenance_note():
    exempt = {p for p in _hits() if p.startswith(RECORDED_DATA)}
    assert all(p.endswith(".truth.json") for p in exempt), sorted(exempt)


def test_AC_llm_banned_models_1_the_guard_reads_the_tree():
    files = _tracked_text_files()
    assert len(files) > 500, len(files)
    for expected in (
        "common/extraction/record_hf_cassettes.py",
        "apps/backend/src/config.py",
        ".github/workflows/ci.yml",
    ):
        assert expected in files, expected


def test_AC_llm_banned_models_1_the_pattern_matches_every_spelling_and_nothing_else():
    for spelling in (
        "glm-4.6v",
        "GLM-4.6V",
        "glm-4.6V",
        "glm4.6v",
        "zai/glm-4.6v",
        "openai/GLM-4.6V",
    ):
        assert BANNED.search(spelling), spelling
    for other in (
        "glm-4.5v",
        "glm-5.3-flash",
        "glm-5.2",
        "glm-4.6",
        "test-vision-model",
        "gpt-4o",
    ):
        assert not BANNED.search(other), other
