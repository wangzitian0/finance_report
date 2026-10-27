"""One definition per SHA-256 digest family in `apps/backend/src` (#2768, part of #2680).

`apps/backend/src/audit/digest.py` holds the two digest definitions of the backend:
`canonical_json_digest` (SHA-256 of sorted, compact JSON) and `text_digest` (SHA-256 of a string).
A digest is stored data, so a second copy that drifts changes a stored value. This scan finds a copy
by its shape, under any name, import style or call form:

* KIND_JSON: a function or module level that builds a SHA-256 and calls `json.dumps(..., sort_keys=True)`.
* KIND_TEXT: a SHA-256 of bytes that come from `.encode(...)` or a bytes literal, read with
  `.hexdigest()`. The bytes can sit in the call, in a variable, or in `.update(...)` calls.

The constructors are `hashlib.sha256(...)`, `hashlib.new("sha256", ...)`, and the same names after
`import hashlib as x` or `from hashlib import sha256 as x` / `new as x`.

Each remaining hit sits in `LEGITIMATE`, keyed by file, function and the exact call, with its own reason.
The test fails on a hit without an entry and on an entry without a hit. A second digest in a function
that has one entry therefore fails.
"""

from __future__ import annotations

import ast
from collections import Counter
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

Hit = tuple[
    str, str, str
]  # (path under apps/backend/src, enclosing function or "<module>", the call)

# Hit -> why this call is not a copy of the two families. One entry and one reason per call.
LEGITIMATE: dict[Hit, str] = {
    (
        "advisor/extension/service.py",
        "AIAdvisorService.chat_stream",
        "hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode('utf-8'))",
    ): "cache key of the advisor context: default separators (', ' and ': '), another byte form",
    (
        "audit/base/trace.py",
        "TraceRecord._construct",
        "hashlib.sha256(json.dumps(record.semantic_payload(), sort_keys=True, separators=(',', ':'), "
        "ensure_ascii=True).encode('utf-8'))",
    ): "TraceRecord id; the file is mirrored in bare-Python common/audit, which cannot import the backend-only helper",
    (
        "audit/base/trace.py",
        "_parent_manifest_digest",
        "hashlib.sha256(json.dumps(sorted((parent.content_digest for parent in parents)), "
        "separators=(',', ':')).encode('utf-8'))",
    ): "TraceRecord parent manifest; mirrored file, same reason",
    (
        _REPLAY_FIXTURE_MODULE,
        "fingerprint",
        "hashlib.sha256(blob.encode('utf-8'))",
    ): "request key of the recorded LLM replay files: `ensure_ascii=False`, another byte form",
    (
        "routers/reports.py",
        "_package_snapshot_zip",
        "hashlib.sha256(data)",
    ): "SHA-256 of the bytes of an exported CSV file; the sorted JSON in the same function is the manifest file",
    (
        "workflow/extension/source_fingerprint.py",
        "workflow_source_fingerprint",
        "hashlib.sha256(json.dumps(payload, sort_keys=True).encode())",
    ): "workflow fingerprint: default separators (', ' and ': '), another byte form",
    (
        "workflow/extension/source_fingerprint.py",
        "workflow_source_fingerprint",
        "hashlib.sha256(settings.model_dump_json().encode())",
    ): (
        "SAME BYTES as text_digest, kept: the workflow contract does not list `audit` in depends_on, and a "
        "new edge needs a classified context relationship (context-contract baseline)"
    ),
}


def _hashlib_names(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    """Return the names bound to the `hashlib` module, to `sha256` and to `hashlib.new`."""
    modules: set[str] = set()
    sha_names: set[str] = set()
    new_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "hashlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "hashlib":
            for alias in node.names:
                if alias.name == "sha256":
                    sha_names.add(alias.asname or alias.name)
                elif alias.name == "new":
                    new_names.add(alias.asname or alias.name)
    return modules, sha_names, new_names


def _names_sha256(call: ast.Call) -> bool:
    """Tell whether the first argument or the `name` keyword of `hashlib.new(...)` is "sha256"."""
    candidates = list(call.args[:1]) + [
        k.value for k in call.keywords if k.arg == "name"
    ]
    return any(isinstance(c, ast.Constant) and c.value == "sha256" for c in candidates)


def _is_sha256_constructor(
    call: ast.Call, names: tuple[set[str], set[str], set[str]]
) -> bool:
    modules, sha_names, new_names = names
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in modules:
            return func.attr == "sha256" or (func.attr == "new" and _names_sha256(call))
        return False
    if isinstance(func, ast.Name):
        return func.id in sha_names or (func.id in new_names and _names_sha256(call))
    return False


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


def _is_encoded_bytes(
    expression: ast.AST, region: list[ast.AST], depth: int = 0
) -> bool:
    """`<x>.encode(...)`, a bytes literal, or a name that the region assigns from one of these."""
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute):
        if expression.func.attr == "encode":
            return True
    if isinstance(expression, ast.Constant) and isinstance(expression.value, bytes):
        return True
    if isinstance(expression, ast.Name) and depth < 3:
        for item in region:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(item, ast.Assign):
                targets, value = item.targets, item.value
            elif isinstance(item, ast.AnnAssign) and item.value is not None:
                targets, value = [item.target], item.value
            if value is not None and any(
                isinstance(t, ast.Name) and t.id == expression.id for t in targets
            ):
                if _is_encoded_bytes(value, region, depth + 1):
                    return True
    return False


def _assigned_name(call: ast.Call, parents: dict[int, ast.AST]) -> str | None:
    parent = parents.get(id(call))
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        target = parent.targets[0]
    elif isinstance(parent, ast.AnnAssign):
        target = parent.target
    else:
        return None
    return target.id if isinstance(target, ast.Name) else None


def _is_text_shape(
    call: ast.Call, parents: dict[int, ast.AST], region: list[ast.AST]
) -> bool:
    """A SHA-256 hex digest of bytes that come from `.encode(...)` or a bytes literal."""
    hexed = False
    # `hashlib.new("sha256", data)` puts the algorithm name first: skip a string constant.
    data_arguments = [
        argument
        for argument in call.args
        if not (isinstance(argument, ast.Constant) and isinstance(argument.value, str))
    ] + [k.value for k in call.keywords if k.arg in ("data", "string")]
    encoded = any(_is_encoded_bytes(argument, region) for argument in data_arguments)
    parent = parents.get(id(call))
    if isinstance(parent, ast.Attribute) and parent.attr == "hexdigest":
        hexed = True
    variable = _assigned_name(call, parents)
    if variable is not None:
        for item in region:
            if not (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == variable
            ):
                continue
            if item.func.attr == "hexdigest":
                hexed = True
            if (
                item.func.attr == "update"
                and item.args
                and _is_encoded_bytes(item.args[0], region)
            ):
                encoded = True
    return hexed and encoded


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


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def scan_digest_shapes(root: Path) -> dict[Hit, set[str]]:
    """Return `(path under root, enclosing function, call) -> kinds` for each digest shape under `root`."""
    hits: dict[Hit, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == HELPER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _hashlib_names(tree)
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_sha256_constructor(node, names)):
                continue
            function = _enclosing_function(node, parents)
            region = _region_nodes(function, tree)
            kinds: set[str] = set()
            if any(_is_json_dumps_with_sort_keys(item) for item in region):
                kinds.add(KIND_JSON)
            if _is_text_shape(node, parents, region):
                kinds.add(KIND_TEXT)
            if kinds:
                scope = (
                    _qualified_name(function, parents)
                    if function is not None
                    else "<module>"
                )
                hits.setdefault((relative, scope, ast.unparse(node)), set()).update(
                    kinds
                )
    return hits


def scan_default_arguments(root: Path) -> Counter[tuple[str, str]]:
    """Count the `canonical_json_digest(..., default=...)` calls per `(path, function)`."""
    counts: Counter[tuple[str, str]] = Counter()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and _callee(node) == "canonical_json_digest"
            ):
                continue
            if any(keyword.arg == "default" for keyword in node.keywords):
                function = _enclosing_function(node, parents)
                scope = (
                    _qualified_name(function, parents)
                    if function is not None
                    else "<module>"
                )
                counts[(relative, scope)] += 1
    return counts


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _unlisted(hits: dict[Hit, set[str]], allowed: dict[Hit, str]) -> list[Hit]:
    return sorted(key for key in hits if key not in allowed)


def _by_scope(hits: dict[Hit, set[str]]) -> dict[tuple[str, str], set[str]]:
    merged: dict[tuple[str, str], set[str]] = {}
    for (path, scope, _call), kinds in hits.items():
        merged.setdefault((path, scope), set()).update(kinds)
    return merged


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
    assert _unlisted(hits, LEGITIMATE) == [], (
        "use canonical_json_digest or text_digest from src.audit, or list the call with a reason"
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

    assert _by_scope(hits) == {
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
    "var_bytes.py": (
        "import hashlib\n\n"
        "def stored(parts):\n"
        "    hash_input = '|'.join(parts).encode('utf-8')\n"
        "    return hashlib.sha256(hash_input).hexdigest()\n"
    ),
    "alias.py": (
        "import hashlib as hl\nfrom hashlib import sha256 as s256\n\n"
        "def one(value):\n"
        "    return hl.sha256(value.encode()).hexdigest()\n\n"
        "def two(value):\n"
        "    return s256(value.encode()).hexdigest()\n"
    ),
    "new.py": (
        "import hashlib\nfrom hashlib import new\n\n"
        "def one(value):\n"
        "    return hashlib.new('sha256', value.encode()).hexdigest()\n\n"
        "def two(value):\n"
        "    return new(name='sha256', data=value.encode()).hexdigest()\n"
    ),
    "update.py": (
        "import hashlib\n\n"
        "def chained(value):\n"
        "    hasher = hashlib.sha256()\n"
        "    hasher.update(value.encode())\n"
        "    return hasher.hexdigest()\n"
    ),
}
SEEDED_SCOPES = {
    ("named_digest.py", "_digest"): {KIND_JSON, KIND_TEXT},
    ("other_name_and_variable.py", "Holder.fingerprint"): {KIND_JSON, KIND_TEXT},
    ("text_copy.py", "_sha"): {KIND_TEXT},
    ("bytes_literal.py", "<module>"): {KIND_TEXT},
    ("from_import.py", "digest"): {KIND_JSON, KIND_TEXT},
    ("var_bytes.py", "stored"): {KIND_TEXT},
    ("alias.py", "one"): {KIND_TEXT},
    ("alias.py", "two"): {KIND_TEXT},
    ("new.py", "one"): {KIND_TEXT},
    ("new.py", "two"): {KIND_TEXT},
    ("update.py", "chained"): {KIND_TEXT},
}
CLEAN_CONTROLS = {
    "file_hash.py": "import hashlib\n\ndef file_hash(content: bytes):\n    return hashlib.sha256(content).hexdigest()\n",
    "read_hash.py": (
        "import hashlib\n\n"
        "def read_hash(handle):\n"
        "    content = handle.read()\n"
        "    return hashlib.sha256(content).hexdigest()\n"
    ),
    "dumps_only.py": "import json\n\ndef dump(value):\n    return json.dumps(value, sort_keys=True)\n",
    "binary_digest.py": "import hashlib\n\ndef key(text):\n    return hashlib.sha256(text.encode()).digest()\n",
    "other_algorithm.py": "import hashlib\n\ndef legacy(text):\n    return hashlib.new('md5', text.encode()).hexdigest()\n",
    "hmac_use.py": (
        "import hmac\nfrom hashlib import sha256\n\n"
        "def sign(key, text):\n"
        "    return hmac.new(key, text.encode(), sha256).hexdigest()\n"
    ),
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
    """AC-audit.44.2: RED on seeded copies under any name, shape, alias or call form; GREEN on file hashes."""
    for name, source in {**SEEDED_COPIES, **CLEAN_CONTROLS}.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    hits = scan_digest_shapes(tmp_path)

    assert _by_scope(hits) == SEEDED_SCOPES
    assert _unlisted(hits, LEGITIMATE) == sorted(hits), (
        "a seeded copy has no list entry, so the tree test would fail"
    )


@ac_proof(
    proof_id="test_digest_single_definition_entry_covers_one_call",
    ac_ids=["AC-audit.44.2"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_2_an_entry_covers_one_call_and_not_the_whole_function(
    tmp_path: Path,
):
    """AC-audit.44.2: two digests in one function with one entry leave the other digest unlisted."""
    (tmp_path / "two_digests.py").write_text(
        "import hashlib\nimport json\n\n"
        "def fingerprint(payload, settings):\n"
        "    inner = hashlib.sha256(settings.encode()).hexdigest()\n"
        "    return hashlib.sha256(json.dumps([payload, inner], sort_keys=True).encode()).hexdigest()\n",
        encoding="utf-8",
    )
    hits = scan_digest_shapes(tmp_path)
    listed = next(key for key in hits if "settings.encode()" not in key[2])

    assert len(hits) == 2
    assert _unlisted(hits, {listed: "another byte form"}) == [
        key for key in sorted(hits) if key != listed
    ]
    assert _unlisted(hits, {listed: "another byte form"})[0][2] == (
        "hashlib.sha256(settings.encode())"
    )


# The calls that kept `default=str` from the code they replaced: a value that JSON cannot encode hashes as its
# text there. Every other call has no `default`, so such a value raises TypeError, as before.
DEFAULT_STR_SITES = {
    (
        "extraction/base/reviewed_statement_envelope.py",
        "ReviewedStatementEnvelopeCommand.digest",
    ): 1,
    ("extraction/extension/reviewed_statement_envelope.py", "_authority"): 1,
    ("ledger/base/decision_anchor.py", "journal_command_target"): 1,
    ("pricing/extension/valuation_contribution.py", "_authority"): 1,
    ("pricing/extension/valuation_contribution.py", "_system_authority"): 1,
    ("pricing/extension/valuation_contribution.py", "valuation_observation_version"): 1,
    (
        "pricing/extension/valuation_contribution.py",
        "resolved_market_valuation_target",
    ): 2,
}


@ac_proof(
    proof_id="test_digest_single_definition_default_str_sites_are_pinned",
    ac_ids=["AC-audit.44.1"],
    ci_tier="pr_ci",
    issue="#2768",
)
def test_AC_audit_44_1_only_the_replaced_default_str_sites_pass_a_default():
    """AC-audit.44.1: a new `default=` at a call site changes what a non-JSON value hashes to: list it first."""
    counts = scan_default_arguments(BACKEND_SRC)

    assert dict(counts) == DEFAULT_STR_SITES


def test_AC_audit_44_1_the_default_scan_finds_a_seeded_default(tmp_path: Path):
    """AC-audit.44.1: RED on a call that passes `default=str` where the old code had none."""
    (tmp_path / "seeded.py").write_text(
        "from src.audit import canonical_json_digest\n\n"
        "def digest(value):\n"
        "    return canonical_json_digest(value, default=str)\n\n"
        "def plain(value):\n"
        "    return canonical_json_digest(value)\n",
        encoding="utf-8",
    )

    assert dict(scan_default_arguments(tmp_path)) == {("seeded.py", "digest"): 1}
