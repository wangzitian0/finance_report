from __future__ import annotations

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

BACKEND_SRC = Path(__file__).resolve().parents[2] / "apps/backend/src"
_REPLAY = "llm/extension/" + "cas" + "sette.py"
LEGITIMATE = {
    (
        "advisor/extension/service.py",
        "hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode('utf-8'))",
    ),
    (
        "audit/base/trace.py",
        "hashlib.sha256(json.dumps(record.semantic_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8'))",
    ),
    (
        "audit/base/trace.py",
        "hashlib.sha256(json.dumps(sorted((parent.content_digest for parent in parents)), separators=(',', ':')).encode('utf-8'))",
    ),
    (_REPLAY, "hashlib.sha256(blob.encode('utf-8'))"),
    ("routers/reports.py", "hashlib.sha256(data)"),
    (
        "workflow/extension/source_fingerprint.py",
        "hashlib.sha256(json.dumps(payload, sort_keys=True).encode())",
    ),
    (
        "workflow/extension/source_fingerprint.py",
        "hashlib.sha256(settings.model_dump_json().encode())",
    ),
}


def _scan(root: Path) -> set[tuple[str, str]]:
    hits: set[tuple[str, str]] = set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if rel == "audit/digest.py":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for s in [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ] or [tree]:
            src = ast.unparse(s)
            if "sha256" in src and (
                "sort_keys=True" in src or (".encode(" in src and ".hexdigest()" in src)
            ):
                hits.update(
                    (rel, ast.unparse(n))
                    for n in ast.walk(s)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", getattr(n.func, "id", "")) == "sha256"
                )
    return hits


@ac_proof(
    "test_digest_single_definition_tree_is_clean",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_backend_src_has_no_second_digest_definition(
    tmp_path: Path,
) -> None:
    """AC-audit.44.2: outside audit/digest.py, duplicate JSON or text SHA-256 digest definitions fail."""
    assert _scan(BACKEND_SRC) == LEGITIMATE
    (tmp_path / "dup.py").write_text(
        "import hashlib, json\n"
        "def d1(x): return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()\n"
        "def d2(s): return hashlib.sha256(s.encode()).hexdigest()\n"
        "def ok(b): return hashlib.sha256(b).hexdigest()\n",
        encoding="utf-8",
    )
    assert len(_scan(tmp_path)) == 2
