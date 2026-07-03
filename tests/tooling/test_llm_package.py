"""llm package — package-model structural invariant guards (#1426 Stage-2 cutover).

These tests prove the structural invariants declared in
``common/llm/contract.py``: the layers converge and stay pure, the published
language equals ``__all__``, the litellm surface stays lazy at the root (so
minimal tooling environments load the package), the cassette record/replay
mechanism lives only in this package (runtime classifies, llm implements), and
the governance gate passes. They are invariant proofs, NOT AC critical-proofs,
so they carry no ``@ac_proof`` (the domain ACs live in the contract roadmap and
are proven by the tests under ``apps/backend/tests/llm/``).
"""

import ast
import subprocess
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
LLM = REPO / "apps/backend/src/llm"

_BACKEND_ROOT = str(REPO / "apps" / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_AC_llm_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.llm as llm_pkg

    from common.llm.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(llm_pkg.__all__)
    assert CONTRACT.name == "llm"
    assert CONTRACT.klass == "infra"
    assert CONTRACT.implementations["be"] == "apps/backend/src/llm"


def test_AC_llm_1_2_converges_by_layer():
    """Invariant converges-by-layer: base/ + extension/ + data/ (and no flat leftovers)."""
    assert (LLM / "base/types.py").exists()
    assert (LLM / "base/protocols.py").exists()
    assert (LLM / "base/config_source.py").exists()
    assert (LLM / "base/secrets.py").exists()
    assert (LLM / "base/usage.py").exists()
    assert (LLM / "extension/client.py").exists()
    assert (LLM / "extension/catalog.py").exists()
    assert (LLM / "extension/routing.py").exists()
    assert (LLM / "extension/cassette.py").exists()
    assert (LLM / "extension/db_config.py").exists()
    assert (LLM / "extension/env_config.py").exists()
    assert (LLM / "extension/factory.py").exists()
    assert (LLM / "data/__init__.py").exists()
    # the pre-cutover flat homes are gone (zero residue)
    assert not (LLM / "common").exists()
    for stray in (
        "cassette.py",
        "catalog.py",
        "client.py",
        "db_config.py",
        "env_config.py",
        "factory.py",
        "routing.py",
        "usage.py",
    ):
        assert not (LLM / stray).exists(), f"flat leftover: {stray}"
    # The LlmProvider/LlmSceneBinding ORM deliberately stays in the unregistered
    # src/models/llm_config.py until its cross-domain FK to users.id is cut
    # (Stage-4 scope; see the contract's unit comment).
    assert (REPO / "apps/backend/src/models/llm_config.py").exists()


def test_AC_llm_1_3_base_layer_is_pure():
    """Invariant base-layer-pure: base/ imports no own extension/, no ORM, no litellm."""
    for py in (LLM / "base").rglob("*.py"):
        mods = _imported_modules(py)
        for mod in mods:
            assert not mod.startswith("src.llm.extension"), (
                f"{py.name} imports extension ({mod}) from base/"
            )
            assert mod != "litellm", f"{py.name} imports litellm from base/"
            assert not mod.startswith("src.database"), (
                f"{py.name} reaches the ORM from base/"
            )


def test_AC_llm_1_4_root_import_is_litellm_free():
    """Invariant no-litellm-at-root: ``import src.llm`` succeeds with litellm blocked.

    Runs in a subprocess with a meta-path blocker so the check is exact even in
    environments where litellm IS installed: any eager import of litellm along
    the root's import chain raises and fails the assertion.
    """
    code = (
        "import sys\n"
        "class _Block:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name == 'litellm' or name.startswith('litellm.') else None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'litellm' or name.startswith('litellm.'):\n"
        "            raise ImportError('litellm blocked: the llm package root must stay litellm-free')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "import src.llm\n"
        "assert len(src.llm.__all__) > 0\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO / "apps" / "backend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"root import pulled litellm eagerly:\n{proc.stderr[-2000:]}"
    )


def test_AC_llm_1_5_cassette_mechanism_only_in_llm():
    """Invariant runtime-classifies-llm-implements: no cassette/replay impl in runtime."""
    assert (LLM / "extension/cassette.py").exists()
    runtime = REPO / "apps/backend/src/runtime"
    for py in runtime.rglob("*.py"):
        offending = [
            mod
            for mod in _imported_modules(py)
            if "cassette" in mod or mod.startswith("src.llm.extension")
        ]
        assert not offending, (
            f"{py.relative_to(REPO)} imports the record/replay mechanism "
            f"({offending}) — it belongs to the llm package (runtime only "
            "classifies the dependency and probes presence)"
        )


def test_AC_llm_1_6_package_contract_gate_passes_for_llm():
    """Invariant passes-own-governance-gate: the gate validates llm with no violations."""
    packages = discover_packages(REPO)
    assert any(p.contract.name == "llm" for p in packages), "llm not discovered"
    ok, messages = run(REPO)
    llm_errors = [m for m in messages if "[llm]" in m]
    assert not llm_errors, f"gate violations for llm: {llm_errors}"
    assert ok, "check_package_contract failed overall"
