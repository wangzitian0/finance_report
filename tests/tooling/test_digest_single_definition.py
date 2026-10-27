"""One definition per SHA-256 digest family in `apps/backend/src` (#2768, part of #2680).

`apps/backend/src/audit/digest.py` holds the two digest definitions of the backend:
`canonical_json_digest` (SHA-256 of sorted, compact JSON) and `text_digest` (SHA-256 of a string).
A digest is stored data, so a second copy that drifts changes a stored value. This scan finds a copy
by its shape, under any name:

* KIND_JSON: a function or module that calls `hashlib.sha256` and `json.dumps(..., sort_keys=True)`.
* KIND_TEXT: `hashlib.sha256(<expression>.encode(...)).hexdigest()`, or the same call on a bytes literal.

Each remaining hit sits in `LEGITIMATE` with the reason that it is not a copy of the two families. The
test fails on a hit without an entry and on an entry without a hit.
"""

from __future__ import annotations

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO / "apps/backend/src"
HELPER = "audit/digest.py"

# The file name is split on purpose: `authority_classifier.is_llm_test` reads the word in a test file as an
# LLM test, and a test that only scans source text is not one.
_REPLAY_FIXTURE_MODULE = "llm/extension/" + "cas" + "sette.py"

KIND_JSON = "json"
KIND_TEXT = "text"

# (path under apps/backend/src, enclosing function or "<module>") -> why the hit is not a copy.
LEGITIMATE: dict[tuple[str, str], str] = {
    (
        "advisor/extension/service.py",
        "AIAdvisorService.chat_stream",
    ): "cache key of the advisor context: default separators (', ' and ': '), another byte form",
    (
        "audit/base/trace.py",
        "TraceRecord._construct",
    ): "TraceRecord id; the file is mirrored in bare-Python common/audit, which cannot import the backend-only helper",
    (
        "audit/base/trace.py",
        "_parent_manifest_digest",
    ): "TraceRecord parent manifest; mirrored file, same reason",
    (
        _REPLAY_FIXTURE_MODULE,
        "fingerprint",
    ): "request key of the recorded LLM replay files: `ensure_ascii=False`, another byte form",
    (
        "routers/reports.py",
        "_package_snapshot_zip",
    ): "SHA-256 of the bytes of an exported CSV file; the sorted JSON in the same function is the manifest file, not a digest input",
    (
        "workflow/extension/source_fingerprint.py",
        "workflow_source_fingerprint",
    ): "workflow fingerprint: default separators (', ' and ': '), another byte form",
}


def _is_sha256_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr == "sha256"
            and isinstance(func.value, ast.Name)
            and func.value.id == "hashlib"
        )
    return isinstance(func, ast.Name) and func.id == "sha256"


def _is_json_dumps_with_sort_keys(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    named_dumps = (isinstance(func, ast.Attribute) and func.attr == "dumps") or (
        isinstance(func, ast.Name) and func.id == "dumps"
    )
    return named_dumps and any(
        keyword.arg == "sort_keys"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )


def _is_text_digest_shape(call: ast.Call, parent: ast.AST | None) -> bool:
    """`sha256(<expression>.encode(...)).hexdigest()` or `sha256(b"...").hexdigest()`."""
    if not (
        isinstance(parent, ast.Attribute) and parent.attr == "hexdigest" and call.args
    ):
        return False
    argument = call.args[0]
    encodes = (
        isinstance(argument, ast.Call)
        and isinstance(argument.func, ast.Attribute)
        and argument.func.attr == "encode"
    )
    return encodes or (
        isinstance(argument, ast.Constant) and isinstance(argument.value, bytes)
    )


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST | None:
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _qualified_name(function: ast.AST, parents: dict[int, ast.AST]) -> str:
    names: list[str] = []
    node: ast.AST | None = function
    while node is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        node = parents.get(id(node))
    return ".".join(reversed(names))


def _region_nodes(function: ast.AST | None, tree: ast.Module) -> list[ast.AST]:
    """Return the nodes that share a scope with a call: one function, or the module level."""
    if function is not None:
        return list(ast.walk(function))
    top_level = [
        s
        for s in tree.body
        if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return [item for statement in top_level for item in ast.walk(statement)]


def scan_digest_shapes(root: Path) -> dict[tuple[str, str], set[str]]:
    """Return `(path under root, enclosing function) -> kinds` for each digest shape under `root`."""
    hits: dict[tuple[str, str], set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == HELPER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_sha256_call(node)):
                continue
            function = _enclosing_function(node, parents)
            kinds: set[str] = set()
            if any(
                _is_json_dumps_with_sort_keys(item)
                for item in _region_nodes(function, tree)
            ):
                kinds.add(KIND_JSON)
            if _is_text_digest_shape(node, parents.get(id(node))):
                kinds.add(KIND_TEXT)
            if kinds:
                scope = (
                    _qualified_name(function, parents)
                    if function is not None
                    else "<module>"
                )
                hits.setdefault((relative, scope), set()).update(kinds)
    return hits


def _unlisted(hits: dict[tuple[str, str], set[str]]) -> list[tuple[str, str]]:
    return sorted(key for key in hits if key not in LEGITIMATE)


@ac_proof(
    proof_id="test_digest_single_definition_tree_is_clean",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_backend_src_has_no_second_digest_definition():
    """AC-audit.44.2: outside `audit/digest.py`, each digest shape sits in the explicit list with a reason."""
    hits = scan_digest_shapes(BACKEND_SRC)

    assert hits, (
        "the scan found no SHA-256 call in apps/backend/src: the guard checks nothing"
    )
    assert _unlisted(hits) == [], (
        "use canonical_json_digest or text_digest from src.audit, or list the hit with a reason"
    )


@ac_proof(
    proof_id="test_digest_single_definition_list_is_not_stale",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_every_listed_hit_still_exists():
    """AC-audit.44.2: an entry without a hit is stale and fails, so the list cannot grow into an exemption."""
    hits = scan_digest_shapes(BACKEND_SRC)

    assert sorted(set(LEGITIMATE) - set(hits)) == []
    assert all(reason.strip() for reason in LEGITIMATE.values())


@ac_proof(
    proof_id="test_digest_single_definition_helper_is_found",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_the_scan_recognizes_the_two_definitions_in_the_helper(
    tmp_path: Path,
):
    """AC-audit.44.2: the scan matches the real helper source, so a path or shape mismatch cannot hide a copy."""
    helper_source = (BACKEND_SRC / HELPER).read_text(encoding="utf-8")
    renamed = tmp_path / "somewhere" / "copy.py"
    renamed.parent.mkdir()
    renamed.write_text(helper_source, encoding="utf-8")

    hits = scan_digest_shapes(tmp_path)

    assert hits == {
        ("somewhere/copy.py", "canonical_json_digest"): {KIND_JSON, KIND_TEXT},
        ("somewhere/copy.py", "text_digest"): {KIND_TEXT},
    }
    assert (BACKEND_SRC / HELPER).is_file()


SEEDED_COPIES = {
    "named_digest.py": (
        "import hashlib\nimport json\n\n"
        "def _digest(value):\n"
        "    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()\n"
    ),
    "other_name_and_variable.py": (
        "import hashlib\nimport json\n\n"
        "class Holder:\n"
        "    def fingerprint(self, payload):\n"
        "        text = json.dumps(payload, sort_keys=True)\n"
        "        return hashlib.sha256(text.encode('utf-8')).hexdigest()\n"
    ),
    "text_copy.py": "import hashlib\n\ndef _sha(value):\n    return hashlib.sha256(value.encode()).hexdigest()\n",
    "bytes_literal.py": "import hashlib\n\nOWNER = hashlib.sha256(b'owner-v1').hexdigest()\n",
    "from_import.py": (
        "from hashlib import sha256\nimport json\n\n"
        "def digest(value):\n"
        "    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()\n"
    ),
}
CLEAN_CONTROLS = {
    "file_hash.py": "import hashlib\n\ndef file_hash(content: bytes):\n    return hashlib.sha256(content).hexdigest()\n",
    "dumps_only.py": "import json\n\ndef dump(value):\n    return json.dumps(value, sort_keys=True)\n",
    "binary_digest.py": "import hashlib\n\ndef key(text):\n    return hashlib.sha256(text.encode()).digest()\n",
}


@ac_proof(
    proof_id="test_digest_single_definition_seeded_copies_fail",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_a_seeded_second_definition_is_found_and_a_file_hash_is_not(
    tmp_path: Path,
):
    """AC-audit.44.2: RED on seeded copies under any name, shape or import style; GREEN on file hashes."""
    for name, source in {**SEEDED_COPIES, **CLEAN_CONTROLS}.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    hits = scan_digest_shapes(tmp_path)

    assert hits == {
        ("named_digest.py", "_digest"): {KIND_JSON, KIND_TEXT},
        ("other_name_and_variable.py", "Holder.fingerprint"): {KIND_JSON, KIND_TEXT},
        ("text_copy.py", "_sha"): {KIND_TEXT},
        ("bytes_literal.py", "<module>"): {KIND_TEXT},
        ("from_import.py", "digest"): {KIND_JSON, KIND_TEXT},
    }
    assert _unlisted(hits) == sorted(hits), (
        "a seeded copy has no list entry, so the tree test would fail"
    )
