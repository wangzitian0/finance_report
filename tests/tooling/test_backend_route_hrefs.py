"""Guard: backend workflow, reporting, and advisor packages emit only target UI routes (#2631).

Loads ``apps/frontend/src/lib/route-map.json`` and inspects ``apps/backend/src/workflow/``,
``apps/backend/src/reporting/``, and ``apps/backend/src/advisor/`` with Python ``ast`` to
ensure no string literal or f-string emits a redirect UI path.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTE_MAP_PATH = REPO_ROOT / "apps" / "frontend" / "src" / "lib" / "route-map.json"
FRONTEND_PATTERNS_PATH = REPO_ROOT / "apps" / "frontend" / "frontend-patterns.md"
BACKEND_PACKAGES = (
    REPO_ROOT / "apps" / "backend" / "src" / "workflow",
    REPO_ROOT / "apps" / "backend" / "src" / "reporting",
    REPO_ROOT / "apps" / "backend" / "src" / "advisor",
)
DYNAMIC_SEGMENT_RE = re.compile(r"\[[^/\]]+\]")
DOC_FILE_REF_RE = re.compile(r"`([^`\n]+\.(?:tsx?|py|json|mjs|css))`")


def load_redirect_route_patterns(
    route_map_path: Path = ROUTE_MAP_PATH,
) -> dict[str, re.Pattern[str]]:
    """Compile anchored regex patterns for every ``state == "redirect"`` route in ``route-map.json``."""
    payload = json.loads(route_map_path.read_text(encoding="utf-8"))
    patterns: dict[str, re.Pattern[str]] = {}
    for entry in payload.get("routes", []):
        if entry.get("state") != "redirect":
            continue
        route_path = str(entry["path"])
        escaped = DYNAMIC_SEGMENT_RE.sub("__DYNAMIC__", route_path)
        escaped = re.escape(escaped).replace("__DYNAMIC__", r"[^/?#]+")
        patterns[route_path] = re.compile(rf"^{escaped}(?:[?#].*)?$")
    return patterns


def _joined_str_template(node: ast.JoinedStr) -> str:
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{expr}")
    return "".join(parts)


def scan_source_for_redirect_hrefs(
    source: str,
    *,
    filename: str = "<memory>",
    redirect_patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[str]:
    """Return violations for any string literal or f-string that matches a redirect route."""
    patterns = (
        redirect_patterns
        if redirect_patterns is not None
        else load_redirect_route_patterns()
    )
    tree = ast.parse(source, filename=filename)
    joined_children: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for child in node.values:
                joined_children.add(id(child))

    violations: list[str] = []
    for node in ast.walk(tree):
        candidate: str | None = None
        if isinstance(node, ast.JoinedStr):
            candidate = _joined_str_template(node)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in joined_children
        ):
            candidate = node.value

        if not candidate or not candidate.startswith("/"):
            continue
        for route_path, pattern in patterns.items():
            if pattern.match(candidate):
                lineno = getattr(node, "lineno", 0)
                violations.append(
                    f"{filename}:{lineno}: {candidate!r} matches redirect route {route_path!r}"
                )
                break
    return violations


def test_AC_platform_36_1_backend_packages_emit_no_redirect_route_hrefs() -> None:
    """AC-platform.36.1: workflow, reporting, and advisor emit target UI routes, never redirect paths."""
    patterns = load_redirect_route_patterns()
    assert "/reports/package" in patterns
    assert "/statements/[id]/review" in patterns
    assert "/review" in patterns

    violations: list[str] = []
    for package_dir in BACKEND_PACKAGES:
        for path in sorted(package_dir.rglob("*.py")):
            rel = str(path.relative_to(REPO_ROOT))
            source = path.read_text(encoding="utf-8")
            violations.extend(
                scan_source_for_redirect_hrefs(
                    source,
                    filename=rel,
                    redirect_patterns=patterns,
                )
            )
    assert violations == [], "Backend emitted redirect UI routes:\n" + "\n".join(
        violations
    )


def test_AC_platform_36_1_redirect_href_scanner_is_falsifiable() -> None:
    """AC-platform.36.1: the AST scanner flags both static redirect literals and dynamic f-strings."""
    synthetic_source = """
def sample(statement):
    a = "/reports/package"
    b = f"/statements/{statement.id}/review"
    c = "/review?source=events"
    ok_a = "/reports?tab=package"
    ok_b = f"/statements/{statement.id}"
    ok_c = "/audit"
    return a, b, c, ok_a, ok_b, ok_c
"""
    violations = scan_source_for_redirect_hrefs(
        synthetic_source, filename="synthetic.py"
    )
    assert len(violations) == 3, violations
    assert any("/reports/package" in item for item in violations)
    assert any("/statements/[id]/review" in item for item in violations)
    assert any("/review" in item for item in violations)


def scan_doc_for_missing_file_refs(
    markdown: str,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Return any backticked relative file path in ``markdown`` that does not exist on disk."""
    search_roots = (
        repo_root,
        repo_root / "apps" / "frontend",
        repo_root / "apps" / "frontend" / "src",
    )
    missing: list[str] = []
    for match in DOC_FILE_REF_RE.finditer(markdown):
        candidate = match.group(1).strip()
        if "/" not in candidate or "*" in candidate or "<" in candidate:
            continue
        if any((root / candidate).is_file() for root in search_roots):
            continue
        missing.append(candidate)
    return missing


def test_AC_platform_36_1_frontend_patterns_cites_only_existing_files() -> None:
    """AC-platform.36.1: apps/frontend/frontend-patterns.md cites only existing file paths."""
    markdown = FRONTEND_PATTERNS_PATH.read_text(encoding="utf-8")
    missing = scan_doc_for_missing_file_refs(markdown)
    assert missing == [], (
        "apps/frontend/frontend-patterns.md cites deleted files:\n" + "\n".join(missing)
    )
    synthetic_missing = scan_doc_for_missing_file_refs(
        "- `app/(main)/statements/page.tsx`\n- `app/(main)/upload/page.tsx`\n"
    )
    assert synthetic_missing == ["app/(main)/statements/page.tsx"]
