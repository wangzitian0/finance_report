"""AC-runtime.sdk-install.1: a workflow job installs the infra2 SDK before it runs a tool that needs the SDK (#2507).

#2496 moved shared helpers into the infra2 SDK. `common/runtime/github_api.py` then imported `infra2_sdk.ci`.
Four workflow jobs ran release tools on a bare Python and failed on that import. The pull request CI did not run
those jobs, so nothing showed it before the merge. This test finds the tools that reach the SDK by a module-level
import. It then checks every workflow job that runs such a tool.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SDK_PACKAGE = "infra2_sdk"
INSTALL_ACTION = "./.github/actions/install-infra2-sdk"
# A step with one of these commands has the SDK in the Python of the job from there on.
INSTALLERS = (
    re.compile(r"pip install[^\n]*(sdk_wheel|infra2[-_]sdk)"),
    re.compile(r"\buv sync\b"),
    re.compile(r"\buv pip install\b"),
    re.compile(r"\buv run\b"),
)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _ModuleImports(ast.NodeVisitor):
    """The imports that run when a module loads. An import inside a function does not."""

    def __init__(self, module: str, is_package: bool) -> None:
        self.module = module
        self.is_package = is_package
        self.found: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]
    visit_Lambda = visit_FunctionDef  # type: ignore[assignment]

    def visit_Import(self, node: ast.Import) -> None:
        self.found.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            package = (
                self.module.split(".")
                if self.is_package
                else self.module.split(".")[:-1]
            )
            package = package[: len(package) - (node.level - 1)]
            base = ".".join(package + ([node.module] if node.module else []))
        self.found.add(base)
        self.found.update(f"{base}.{alias.name}" for alias in node.names)


def _import_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for top in ("common", "tools"):
        for path in (ROOT / top).rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            visitor = _ModuleImports(_module_name(path), path.name == "__init__.py")
            visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
            graph[visitor.module] = visitor.found
    return graph


def _reaches_sdk(module: str, graph: dict[str, set[str]], seen: set[str]) -> bool:
    if module in seen:
        return False
    seen.add(module)
    for dependency in graph.get(module, ()):
        if dependency.split(".")[0] == SDK_PACKAGE:
            return True
        if dependency in graph and _reaches_sdk(dependency, graph, seen):
            return True
    return False


def _sdk_tools() -> set[str]:
    """The top-level tools (`tools/<name>.py`) that load the SDK when they start."""
    graph = _import_graph()
    return {
        module.split(".", 1)[1]
        for module in graph
        if module.startswith("tools.")
        and module.count(".") == 1
        and _reaches_sdk(module, graph, set())
    }


def _runs_tool(command: str, tools: set[str]) -> str | None:
    for name in sorted(tools):
        if re.search(
            rf"(?<![\w/])tools/{re.escape(name)}\.(py|sh)\b|python3? -m tools\.{re.escape(name)}\b",
            command,
        ):
            return name
    return None


def _installs_sdk(step: dict[str, object]) -> bool:
    if str(step.get("uses", "")) == INSTALL_ACTION:
        return True
    command = str(step.get("run", ""))
    return any(pattern.search(command) for pattern in INSTALLERS)


def _jobs_without_sdk(tools: set[str]) -> list[str]:
    """Each workflow job that runs an SDK tool before it installs the SDK."""
    violations: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (workflow.get("jobs") or {}).items():
            installed = False
            for number, step in enumerate(job.get("steps") or []):
                installed = installed or _installs_sdk(step)
                tool = _runs_tool(str(step.get("run", "")), tools)
                if tool and not installed:
                    violations.append(
                        f"{path.name}:{job_id}: step {number} runs tools/{tool} before the SDK install"
                    )
                    break
    return violations


def test_AC_runtime_sdk_install_1_the_scan_finds_the_tools_that_need_the_sdk() -> None:
    tools = _sdk_tools()

    # These tools reach `infra2_sdk` by a module-level import today. A tool that drops the import leaves the set.
    assert {
        "resolve_release_coordinate",
        "verify_release_evidence",
        "verify_release_images",
    } <= tools
    # A tool that imports only the standard library is not in the set.
    assert "sdk_pin" not in tools


def test_AC_runtime_sdk_install_1_every_job_installs_the_sdk_before_it_runs_a_tool_that_needs_it() -> (
    None
):
    assert _jobs_without_sdk(_sdk_tools()) == []


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([{"run": "python tools/verify_release_images.py --help"}], 1),
        ([{"run": "python3 tools/resolve_release_coordinate.py --version-ref v1"}], 1),
        ([{"run": "python -m tools.verify_release_evidence --check staging"}], 1),
        (
            [
                {"uses": INSTALL_ACTION},
                {"run": "python tools/verify_release_images.py"},
            ],
            0,
        ),
        ([{"run": "uv sync"}, {"run": "python tools/verify_release_images.py"}], 0),
        (
            [
                {"run": 'python -m pip install "$sdk_wheel"'},
                {"run": "python tools/verify_release_images.py"},
            ],
            0,
        ),
        (
            [
                {"run": "python tools/verify_release_images.py"},
                {"uses": INSTALL_ACTION},
            ],
            1,
        ),
        ([{"run": "python tools/sdk_pin.py"}], 0),
        (
            [
                {"run": "uv tool install uv"},
                {"run": "python tools/verify_release_images.py"},
            ],
            1,
        ),
    ],
)
def test_AC_runtime_sdk_install_1_the_scan_catches_a_tool_that_runs_before_the_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[dict[str, str]],
    expected: int,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "probe.yml").write_text(
        yaml.safe_dump({"jobs": {"probe": {"steps": steps}}}), encoding="utf-8"
    )
    monkeypatch.setattr(f"{__name__}.WORKFLOWS", workflows)

    assert len(_jobs_without_sdk(_sdk_tools())) == expected
