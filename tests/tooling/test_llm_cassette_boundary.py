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
# The entry point of the app is the one caller of these (the guard of the tests against a model call inside an open
# transaction wraps it).
_ENTRY_POINT_ONLY_NAMES = ("create_llm_agent", "create_llm_model")
_ENTRY_POINT = "apps/backend/src/llm/extension/agent.py"


def _is_test_only_module(module: str) -> bool:
    return any(module == banned or module.startswith(banned + ".") for banned in _TEST_ONLY_MODULES)


def _dotted(node: object) -> str | None:
    import ast

    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def imports_of_test_doubles_in(source: str, *, entry_point: bool = False) -> list[str]:
    """Return the uses of a fake model, a recorder, or (outside the entry point) the SDK agent factory in ``source``.

    The forms: ``import m``, ``from m import n``, ``from pydantic_ai.models import function`` (a submodule by
    name), ``from m import *``, an attribute chain such as ``pydantic_ai.models.function.FunctionModel``, and a
    string that is a module name (``importlib.import_module("...")``, ``__import__("...")``).
    """
    import ast
    import re

    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits.extend(f"import {alias.name}" for alias in node.names if _is_test_only_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_test_only_module(module):
                hits.append(f"from {module} import ...")
            for alias in node.names:
                if alias.name in _TEST_ONLY_NAMES or _is_test_only_module(f"{module}.{alias.name}"):
                    hits.append(f"from {module} import {alias.name}")
                if alias.name == "*" and module.startswith("pydantic_ai.models"):
                    hits.append(f"from {module} import *")
                if not entry_point and alias.name in _ENTRY_POINT_ONLY_NAMES:
                    hits.append(f"from {module} import {alias.name}")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted and _is_test_only_module(dotted):
                hits.append(f"attribute {dotted}")
            if not entry_point and node.attr in _ENTRY_POINT_ONLY_NAMES:
                hits.append(f"attribute {dotted or node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"[A-Za-z_][\w.]*", node.value) and _is_test_only_module(node.value):
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
        "from pydantic_ai.models import *",
        "import pydantic_ai.models\nx = pydantic_ai.models.function.FunctionModel",
        'importlib.import_module("pydantic_ai.models.function")',
        '__import__("vcr")',
        "from infra2_sdk.runtime import create_llm_agent",
        "import infra2_sdk.runtime as r\nr.create_llm_model()",
    ]
    assert [form for form in forms if not imports_of_test_doubles_in(form)] == []
    clean = "import json\nfrom pydantic_ai import ImageUrl\nfrom pydantic_ai.models import Model\nx = 'vcrx'\ny = 'vcr.py cassette'"
    assert imports_of_test_doubles_in(clean) == []
    # The entry point may call the factory.
    assert imports_of_test_doubles_in("from infra2_sdk.runtime import create_llm_agent", entry_point=True) == []


def test_product_code_imports_no_model_test_double_and_no_recorder() -> None:
    """#3153: a fake model and a recording belong to tests; product code reaches a model through the entry point."""
    src = ROOT / "apps/backend/src"
    files = [path for path in src.rglob("*.py") if "__pycache__" not in path.parts]
    hits = [
        f"{path.relative_to(ROOT).as_posix()}: {hit}"
        for path in files
        for hit in imports_of_test_doubles_in(
            path.read_text(encoding="utf-8"), entry_point=path.relative_to(ROOT).as_posix() == _ENTRY_POINT
        )
    ]
    # The scan must read the entry point, or an empty scan would pass.
    assert (src / "llm/extension/agent.py") in files and len(files) > 100
    assert hits == []
