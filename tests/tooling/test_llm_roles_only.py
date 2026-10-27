"""AC-llm.roles-only.1: the app has three model environment keys, one per SDK role (#2643).

The owner rule: large, small and multimodal. No custom model by default; the user brings a token.
These tests read the real files, so a fourth model key, a retired slot name or a second way to
set a model fails them.
"""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THREE_ROLES = {"LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL"}
RETIRED_ENV = {
    "PRIMARY_MODEL",
    "VISION_MODEL",
    "OCR_MODEL",
    "FALLBACK_MODELS",
    "VISION_FALLBACK_MODELS",
}
RETIRED_ATTR = {
    "primary_model",
    "vision_model",
    "ocr_model",
    "fallback_models",
    "vision_fallback_models",
    "fallback_models_str",
}
RETIRED_NAME = re.compile(
    r"\b(" + "|".join(sorted(RETIRED_ATTR)) + r"|_OcrMixin|_vision_extraction_models)\b"
)


def _manifest_env_names() -> set[str]:
    manifest = json.loads(
        (ROOT / "common/runtime/required-env.generated.json").read_text(
            encoding="utf-8"
        )
    )
    return {field["env"] for field in manifest["fields"]}


def test_AC_llm_roles_only_1_the_model_env_keys_are_exactly_the_three_roles():
    names = _manifest_env_names()
    assert len(names) > 50, "the guard must read the whole manifest"
    model_keys = {name for name in names if "MODEL" in name}
    assert model_keys == THREE_ROLES, sorted(model_keys ^ THREE_ROLES)


def test_AC_llm_roles_only_1_no_retired_slot_name_is_an_env_key_or_an_example():
    names = _manifest_env_names()
    assert not (names & RETIRED_ENV), sorted(names & RETIRED_ENV)
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    example_keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    assert THREE_ROLES <= example_keys
    assert not (example_keys & RETIRED_ENV), sorted(example_keys & RETIRED_ENV)


def test_AC_llm_roles_only_1_no_source_file_names_a_retired_slot():
    # Any object, not only `settings`: the extraction service once held its own
    # `ocr_model` and `vision_model` copies of the multimodal role (#2681).
    scanned = 0
    hits: list[str] = []
    for path in (ROOT / "apps/backend/src").rglob("*.py"):
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RETIRED_NAME.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert scanned > 200, scanned
    assert not hits, hits


def test_AC_llm_roles_only_1_the_app_hands_only_the_three_roles_to_the_sdk():
    tree = ast.parse((ROOT / "apps/backend/src/config.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "LlmSettings"
        and node.keywords
    ]
    assert calls, "config.py must build LlmSettings with keywords"
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert {"large_model", "small_model", "multimodal_model"} <= keywords
        assert not (keywords & RETIRED_ATTR), sorted(keywords & RETIRED_ATTR)


def test_AC_llm_roles_only_1_the_guard_sees_a_fourth_model_key_and_a_retired_name():
    # A guard that never fails proves nothing: feed it the shapes it must reject.
    assert {
        "LARGE_MODEL",
        "SMALL_MODEL",
        "MULTIMODAL_MODEL",
        "EXTRA_MODEL",
    } != THREE_ROLES
    assert RETIRED_NAME.search("name = settings.primary_model")
    assert RETIRED_NAME.search("if model == settings.ocr_model:")
    # The shapes that ExtractionService held before #2681.
    assert RETIRED_NAME.search("self.vision_model = self.multimodal_model")
    assert RETIRED_NAME.search("class ExtractionService(_MediaMixin, _OcrMixin):")
    assert RETIRED_NAME.search("models = self._vision_extraction_models()")
    assert not RETIRED_NAME.search("name = settings.small_model")
    assert not RETIRED_NAME.search("model = force_model or self.multimodal_model")
