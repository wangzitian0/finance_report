'AC-llm.10.7'; from __future__ import annotations; from pathlib import Path; ROOT = Path(__file__).resolve().parents[2]; _ALLOWED = ('apps/backend/src/llm/', 'apps/backend/tests/llm/', 'apps/backend/tests/conftest.py', 'common/llm/', 'common/meta/extension/authority_classifier.py', 'tests/tooling/test_authority_classifier.py', 'apps/backend/tests/ai/test_ai_streaming.py', 'apps/backend/src/config.py', 'tests/tooling/test_llm_cassette_boundary.py'); _BANNED = ('CassetteMode', 'current_mode', 'CassetteRecorder', 'cassette_completion', 'LLM_CASSETTE_MODE', 'LLM_CASSETTE_ENGAGE', 'LLM_CASSETTE_REFRESH', 'LLM_LIVE', 'src.llm.extension.cassette'); _SCAN_ROOTS = ('apps/backend/src', 'apps/backend/tests', 'tests', 'common', 'tools')
def test_AC_llm_10_7_no_cassette_knowledge_outside_the_layer() -> None:
    'AC-llm.10.7'; hits: list[str] = []
    for base in _SCAN_ROOTS:
        root = ROOT / base
        if not root.exists(): continue
        for path in root.rglob('*.py'):
            rel = path.relative_to(ROOT).as_posix()
            if any((rel.startswith(a) or rel == a for a in _ALLOWED)): continue
            if '__pycache__' in path.parts or '.venv' in path.parts: continue
            text = path.read_text(encoding='utf-8', errors='ignore'); [hits.append(f'{rel}: {token}') if token in text else None for token in _BANNED]
    assert hits == [], f"downstream code references the cassette layer's internals/knobs (the layer decides per request; downstream must not know): {hits}"


_TEST_ONLY_IMPORTS = ("vcr", "pytest_recording", "pydantic_ai.models.test", "pydantic_ai.models.function")
_TEST_ONLY_NAMES = ("TestModel", "FunctionModel")


def test_product_code_imports_no_model_test_double_and_no_recorder() -> None:
    """#3153: a fake model and a recording belong to tests. Product code gets a model through `override_model` only."""
    import ast

    src = ROOT / "apps/backend/src"
    files = [path for path in src.rglob("*.py") if "__pycache__" not in path.parts]
    hits: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            names = [alias.name for alias in node.names] if isinstance(node, ast.ImportFrom) else []
            for module in modules:
                if any(module == banned or module.startswith(banned + ".") for banned in _TEST_ONLY_IMPORTS):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}: import {module}")
            hits.extend(
                f"{path.relative_to(ROOT).as_posix()}: name {name}" for name in names if name in _TEST_ONLY_NAMES
            )
    # The scan must read the entry point, or an empty scan would pass.
    assert (src / "llm/extension/agent.py") in files and len(files) > 100
    assert hits == []
