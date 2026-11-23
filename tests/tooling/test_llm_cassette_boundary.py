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


_TEST_ONLY_MODULES = ("vcr", "pytest_recording", "pydantic_ai.models.test", "pydantic_ai.models.function")
_TEST_ONLY_NAMES = ("TestModel", "FunctionModel")


def _is_test_only_module(module: str) -> bool:
    return any(module == banned or module.startswith(banned + ".") for banned in _TEST_ONLY_MODULES)


def imports_of_test_doubles_in(source: str) -> list[str]:
    """Return the imports of a fake model or a recorder in ``source``, in each form that Python allows.

    The forms: ``import m``, ``from m import n``, ``from pydantic_ai.models import function`` (a submodule by
    name), and a string that names such a module (``importlib.import_module("...")``, ``__import__("...")``).
    """
    import ast

    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits.extend(f"import {alias.name}" for alias in node.names if _is_test_only_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_test_only_module(module):
                hits.append(f"from {module} import ...")
            hits.extend(
                f"from {module} import {alias.name}"
                for alias in node.names
                if alias.name in _TEST_ONLY_NAMES or _is_test_only_module(f"{module}.{alias.name}")
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _is_test_only_module(node.value):
            hits.append(f"string {node.value!r}")
    return hits


def test_the_scan_of_test_only_imports_knows_each_import_form() -> None:
    forms = [
        "import vcr",
        "from vcr import VCR",
        "import pytest_recording",
        "import pydantic_ai.models.function as x",
        "from pydantic_ai.models.function import FunctionModel",
        "from pydantic_ai.models import function",
        "from pydantic_ai.models import test as t",
        "from pydantic_ai.models import TestModel",
        'importlib.import_module("pydantic_ai.models.function")',
        '__import__("vcr")',
    ]
    assert all(imports_of_test_doubles_in(form) for form in forms)
    clean = "import json\nfrom pydantic_ai import ImageUrl\nfrom pydantic_ai.models import Model\nx = 'vcrx'"
    assert imports_of_test_doubles_in(clean) == []


def test_product_code_imports_no_model_test_double_and_no_recorder() -> None:
    """#3153: a fake model and a recording belong to tests. Product code reaches a model through the entry point."""
    src = ROOT / "apps/backend/src"
    files = [path for path in src.rglob("*.py") if "__pycache__" not in path.parts]
    hits = [
        f"{path.relative_to(ROOT).as_posix()}: {hit}"
        for path in files
        for hit in imports_of_test_doubles_in(path.read_text(encoding="utf-8"))
    ]
    # The scan must read the entry point, or an empty scan would pass.
    assert (src / "llm/extension/agent.py") in files and len(files) > 100
    assert hits == []
