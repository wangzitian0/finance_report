from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from common.meta.extension import dependency_report


def test_AC_meta_public_boundary_1_snapshot_is_complete_and_single_source(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.1: all boundary kinds share one snapshot."""
    (tmp_path / "apps/frontend/src").mkdir(parents=True)
    (tmp_path / "apps/frontend/openapi.json").write_text(
        '{"paths":{"/things/{thing_id}":{"get":{"operationId":"get_thing"}}}}',
        encoding="utf-8",
    )
    (tmp_path / "apps/frontend/src/things.ts").write_text(
        'apiOperation("get_thing", { path: { thing_id: "1" } });\n',
        encoding="utf-8",
    )

    records = dependency_report.discover_delivery_boundaries(tmp_path)

    assert {(row["kind"], row["id"]) for row in records} == {
        ("openapi-operation", "get_thing"),
        ("frontend-operation-consumer", "get_thing@apps/frontend/src/things.ts:1"),
    }


def test_AC_meta_public_boundary_1_snapshot_projects_delivery_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-meta.public-boundary.1: delivery records are part of the shared snapshot."""
    monkeypatch.setattr(
        dependency_report,
        "_snapshot_packages",
        lambda _root: [dependency_report.SnapshotPackage("demo", (), (), (), None)],
    )
    monkeypatch.setattr(
        dependency_report,
        "discover_delivery_boundaries",
        lambda _root: [{"kind": "openapi-operation", "id": "get_thing"}],
    )

    snapshot = dependency_report.build_dependency_snapshot(tmp_path)

    assert snapshot["delivery_boundaries"] == [
        {"kind": "openapi-operation", "id": "get_thing"}
    ]


def test_AC_meta_public_boundary_2_financial_signatures_fail_closed() -> None:
    """AC-meta.public-boundary.2: dynamic financial command seams are rejected."""
    records = [
        {
            "package": "ledger",
            "symbol": "post_entries",
            "signature": "def(entries: list[dict], currency, posted_at) -> Any",
            "command_boundary": True,
        },
        {
            "package": "extraction",
            "symbol": "approve_statement",
            "signature": "def(command: ApproveStatement) -> ApprovalResult",
            "command_boundary": True,
        },
    ]

    assert dependency_report.financial_signature_findings(records) == [
        {
            "package": "ledger",
            "symbol": "post_entries",
            "codes": [
                "dynamic-mapping",
                "missing-currency-type",
                "missing-date-type",
                "dynamic-return",
            ],
        }
    ]


def test_AC_meta_public_boundary_3_frontend_uses_generated_operations(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.3: production calls cannot assert path/type separately."""
    source = tmp_path / "apps/frontend/src/page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        'apiFetch<Thing>("/api/things/1", { method: "GET" });\n',
        encoding="utf-8",
    )

    records = dependency_report.discover_frontend_operation_consumers(tmp_path)

    assert records[0]["classification"] == "untyped-api-fetch"
    assert records[0]["blocking"] is True


def test_AC_meta_public_boundary_3_scans_all_transports_and_ignores_comments(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.3: every production transport has one operation seam."""
    source = tmp_path / "apps/frontend/src/page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """// apiFetch('/not-code')
/* apiDownload('/also-not-code') */
apiOperationDownload(
  "download_thing",
  { path: { thing_id: "1" } },
);
useApiQuery(["thing"], "get_thing", {});
apiUpload('/legacy', new FormData());
""",
        encoding="utf-8",
    )

    records = dependency_report.discover_frontend_operation_consumers(tmp_path)

    assert [(row["classification"], row["operation_id"]) for row in records] == [
        ("generated-operation", "download_thing"),
        ("generated-operation", "get_thing"),
        ("untyped-api-fetch", None),
    ]


def test_AC_meta_public_boundary_4_breaking_consumers_block() -> None:
    """AC-meta.public-boundary.4: every impacted consumer needs an exact proof."""
    report = {
        "removed_public_symbols": [
            {"package": "provider", "symbol": "old", "signature": "def() -> str"}
        ],
        "changed_public_symbols": [],
        "affected_consumers": {
            "provider": {
                "direct": ["middle"],
                "transitive": ["app", "middle"],
                "indirect": ["app"],
            }
        },
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report,
        consumer_proofs={"middle": {"result": "passed", "strength": "exact"}},
    )

    assert result["status"] == "blocked"
    assert result["unproved_consumers"] == ["app"]
    assert result["breaking_changes"][0]["kind"] == "removed-public-symbol"


def test_AC_meta_public_boundary_4_openapi_change_requires_frontend_source_proof() -> (
    None
):
    """AC-meta.public-boundary.4: OpenAPI consumers are explicit proof subjects."""
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [
            {"kind": "openapi-operation", "id": "get_thing"}
        ],
        "affected_consumers": {},
        "base": {
            "delivery_boundaries": [
                {
                    "kind": "frontend-operation-consumer",
                    "operation_id": "get_thing",
                    "source": "apps/frontend/src/page.tsx",
                }
            ]
        },
        "head": {"delivery_boundaries": []},
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "blocked"
    assert result["unproved_consumers"] == ["apps/frontend/src/page.tsx"]


def test_AC_meta_public_boundary_4_defaulted_field_and_annotation_propagation_are_compatible() -> (
    None
):
    """AC-meta.public-boundary.4: compatible additions do not create fake migrations."""
    changed_type = {
        "package": "meta",
        "symbol": "Contract",
        "before": "pkg.py::Contract => class(BaseModel){name: str; active: bool=True}",
        "after": (
            "pkg.py::Contract => class(BaseModel){name: str; "
            "labels: list[str]=[]; active: bool=True}"
        ),
    }
    unchanged_declaration = {
        "package": "meta",
        "symbol": "project",
        "before": (
            "pkg.py::project => def(value: Contract) -> str "
            "[annotations: Contract=class(BaseModel){name: str}]"
        ),
        "after": (
            "pkg.py::project => def(value: Contract) -> str "
            "[annotations: Contract=class(BaseModel){name: str; labels: list[str]=[]}]"
        ),
    }
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [changed_type, unchanged_declaration],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [],
        "affected_consumers": {},
        "head": {"delivery_boundaries": [], "public_symbols": []},
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "compatible"
    assert result["breaking_changes"] == []


def test_AC_meta_public_boundary_4_nested_enum_addition_is_not_a_dto_break() -> None:
    """AC-meta.public-boundary.4: recursive enum growth is not a DTO declaration change."""
    before_enum = "class(str, Enum){ACTIVE='active'; FAILED='failed'}"
    after_enum = "class(str, Enum){ACTIVE='active'; FAILED='failed'; RETIRED='retired'}"
    changed_dto = {
        "package": "extraction",
        "symbol": "Source",
        "before": (
            "pkg.py::Source => class(Base){status: Mapped[Status]="
            f"mapped_column(Status.ACTIVE) [Status={before_enum}]}}"
        ),
        "after": (
            "pkg.py::Source => class(Base){status: Mapped[Status]="
            f"mapped_column(Status.ACTIVE) [Status={after_enum}]}}"
        ),
    }
    changed_public_enum = {
        "package": "extraction",
        "symbol": "Status",
        "before": f"pkg.py::Status => {before_enum}",
        "after": f"pkg.py::Status => {after_enum}",
    }
    changed_enum_value = {
        **changed_dto,
        "after": changed_dto["after"].replace("FAILED='failed'", "FAILED='error'"),
    }
    removed_enum_member = {
        **changed_public_enum,
        "before": changed_public_enum["after"],
        "after": changed_public_enum["before"],
    }

    assert dependency_report._is_compatible_public_change(changed_dto)
    assert dependency_report._is_compatible_public_change(changed_public_enum)
    assert not dependency_report._is_compatible_public_change(changed_enum_value)
    assert not dependency_report._is_compatible_public_change(removed_enum_member)


def test_AC_meta_public_boundary_5_existing_gate_enforces_and_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-meta.public-boundary.5: the report exits red and emits observations."""
    report = {
        "added_edges": [],
        "removed_edges": [],
        "added_public_symbols": [],
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "affected_consumers": {},
        "compatibility": {
            "status": "blocked",
            "breaking_changes": [{"kind": "untyped-api-fetch", "id": "page.tsx:1"}],
            "unproved_consumers": [],
        },
    }
    monkeypatch.setattr(
        dependency_report, "build_impact_report", lambda _root, base_ref: report
    )
    observations = tmp_path / "observations.json"

    exit_code = dependency_report.main(
        [
            "--repo-root",
            str(tmp_path),
            "--base-ref",
            "base",
            "--fail-on-breaking",
            "--governance-observations-out",
            str(observations),
        ]
    )

    assert exit_code == 1
    payload = json.loads(observations.read_text(encoding="utf-8"))
    assert payload["source"] == "package-detector"
    assert set(payload) == {"source", "target_sha", "observed_at", "detectors"}
    guarantee_ids = {item["guarantee_id"] for item in payload["detectors"]}
    assert {"meta/one-boundary-graph", "meta/enforced-compatibility"} <= guarantee_ids


def test_AC_meta_public_boundary_5_untyped_and_unknown_consumers_block() -> None:
    """AC-meta.public-boundary.5: current delivery violations cannot be reported green."""
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [],
        "affected_consumers": {},
        "head": {
            "public_symbols": [],
            "delivery_boundaries": [
                {"kind": "openapi-operation", "id": "known"},
                {
                    "kind": "frontend-operation-consumer",
                    "id": "untyped@app/page.tsx:1",
                    "classification": "untyped-api-fetch",
                },
                {
                    "kind": "frontend-operation-consumer",
                    "id": "missing@app/page.tsx:2",
                    "classification": "generated-operation",
                    "operation_id": "missing",
                },
            ],
        },
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "blocked"
    assert [row["kind"] for row in result["breaking_changes"]] == [
        "untyped-api-fetch",
        "unknown-openapi-operation",
    ]


def _signature_from_source(source: str, tmp_path: Path) -> str:
    """Exercise the actual producer format, including decorators and method names."""
    module = ast.parse(source)
    node = module.body[0]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return dependency_report._function_signature(node, tmp_path)
    assert isinstance(node, ast.ClassDef)
    return dependency_report._class_signature(
        node,
        module_body=module.body,
        values={},
        source=tmp_path / "public.py",
        repo_root=tmp_path,
        seen=frozenset(),
        definition_index=0,
    )


@pytest.mark.parametrize("case", ["row", "income", "staticmethod", "new_method"])
def test_AC_meta_public_boundary_8_real_additive_surfaces(
    tmp_path: Path, case: str
) -> None:
    """AC-meta.public-boundary.8: actual PDF-chain declarations do not invent consumer migrations."""
    sources = {
        "row": (
            "@dataclass(frozen=True, slots=True, kw_only=True)\nclass ExtractedTransactionRow:\n"
            "    user_id: UUID\n    txn_date: date\n    amount: Decimal\n    direction: str\n"
            "    description: str\n    reference: str | None\n    currency: str\n"
            "    currency_unresolved: bool\n    balance_after: Decimal | None\n"
            "    occurrence_index: int\n    dedup_hash: str\n",
            "    custody_scope: str | None = None\n",
        ),
        "income": (
            "async def generate_income_statement(db: AsyncSession, user_id: UUID, *, "
            "start_date: date, end_date: date, currency: str | None=None, tags: list[str] | None=None, "
            "account_type: AccountType | None=None) -> dict[str, object]: pass",
            ", include_economic_categories: bool=False",
        ),
        "staticmethod": (
            "class DeduplicationService:\n    @staticmethod\n"
            "    def calculate_transaction_hash(user_id: UUID, txn_date: date, amount: Decimal, "
            "direction: TransactionDirection, description: str, reference: str | None=None, "
            "balance_after: Decimal | None=None, occurrence_index: int=0) -> str: pass\n",
            ", *, currency: str | None=None, custody_scope: str | None=None",
        ),
        "new_method": (
            "class EvidenceGraphMaterializationService:\n    def __init__(self) -> None: pass\n"
            "    def detect_consistency_drift(self, db: AsyncSession, *, user_id: UUID | None=None) "
            "-> EvidenceConsistencyReport: pass\n",
            "    async def validate_opening_nodes(self, db: AsyncSession, *, user_id: UUID, "
            "nodes: list[EvidenceNode]) -> list[EvidenceMaterializationBlocker]: pass\n",
        ),
    }
    before, addition = sources[case]
    after = (
        before + addition
        if case in {"row", "new_method"}
        else before.replace(") ->", addition + ") ->")
    )
    record = {
        "package": "demo",
        "symbol": "Surface",
        "before": _signature_from_source(before, tmp_path),
        "after": _signature_from_source(after, tmp_path),
    }
    result = dependency_report.evaluate_boundary_compatibility(
        {
            "changed_public_symbols": [record],
            "head": {"delivery_boundaries": [], "public_symbols": []},
        },
        consumer_proofs={},
    )
    assert result["status"] == "compatible", result["breaking_changes"]
    assert result["breaking_changes"] == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "def(value: int, *args: str) -> int",
            "def(value: int, *args: str, flag: bool=False) -> int",
        ),
        ("def(*, value: int) -> int", "def(*, flag: bool=False, value: int) -> int"),
        (
            "@dataclass class(){value: int}",
            "@dataclass class(){value: int; label: str='a; } b=(c)'}",
        ),
        (
            "@dataclass(frozen=True) class(){value: int}",
            "@dataclass(frozen=True) class(){value: int; labels: list[str]=field(default_factory=list)}",
        ),
        (
            "class(BaseModel){value: int}",
            "class(BaseModel){value: int; labels: list[str]=Field(default_factory=list)}",
        ),
        (
            "class(){@classmethod create(cls, value: int) -> int}",
            "class(){@classmethod create(cls, value: int, *, flag: bool=False) -> int}",
        ),
    ],
)
def test_AC_meta_public_boundary_8_preserves_additive_bindings(
    before: str, after: str
) -> None:
    """AC-meta.public-boundary.8: delimiters in strings and preserved variadic positions are data."""
    assert dependency_report._is_compatible_public_change(
        {"before": before, "after": after}
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("def(value: int) -> int", "def(value: int, extra: int=0) -> int"),
        ("def(value: int, /) -> int", "def(value: int) -> int"),
        ("def(value: int) -> int", "def(renamed: int) -> int"),
        ("def(value: int) -> int", "def(value: str) -> int"),
        ("def(value: int=1) -> int", "def(value: int=2) -> int"),
        ("def(*, value: int) -> int", "def(*, value: int=0) -> int"),
        ("def(value: int) -> int", "def(value: int) -> int | None"),
        ("def(value: int) -> int", "async def(value: int) -> int"),
        ("def(value: int) -> int", "def(value: int, *, extra: int) -> int"),
        (
            "def(*, value: int) -> int",
            "def(*, value: int, extra: Annotated[int, 'x=y']) -> int",
        ),
        ("def(*args: int) -> int", "def(value: int=0, *args: int) -> int"),
        ("def(*args: int) -> int", "def(*args: str, flag: bool=False) -> int"),
        ("def(*args: int) -> int", "def(*values: int, flag: bool=False) -> int"),
        (
            "def(**kwargs: object) -> int",
            "def(*, flag: bool=False, **kwargs: object) -> int",
        ),
        ("def(value: int) -> int", "def(value: int, **kwargs: object) -> int"),
        (
            "def(*, first: int, second: int) -> int",
            "def(*, second: int, first: int, extra: bool=False) -> int",
        ),
        (
            "def(value: int=LIMIT) -> int [defaults: LIMIT=1]",
            "def(value: int=LIMIT, *, flag: bool=False) -> int [defaults: LIMIT=2]",
        ),
        (
            "class(){@staticmethod call(value: int) -> int}",
            "class(){@classmethod call(value: int, *, flag: bool=False) -> int}",
        ),
        (
            "class(){call(self, value: int=1) -> int}",
            "class(){call(self, value: int=2, *, flag: bool=False) -> int}",
        ),
        (
            "class(){call(self) -> int}",
            "class(){call(self, *, flag: bool=False) -> int | None}",
        ),
        (
            "class(){upsert(self, *, row: Row | None=None, **legacy_fields: object) -> Row}",
            "class(){upsert(self, *, row: Row | None=None, custody_account_id: UUID | None=None, **legacy_fields: object) -> Row}",
        ),
        (
            "@dataclass(frozen=True) class(){value: int}",
            "@dataclass(frozen=False) class(){value: int; extra: int=0}",
        ),
        (
            "@dataclass(kw_only=True) class(){value: int}",
            "@dataclass class(){value: int; extra: int=0}",
        ),
        (
            "@dataclass class(){first: int; second: int=0}",
            "@dataclass class(){first: int; extra: int=0; second: int=0}",
        ),
        (
            "@dataclass class(){first: int; second: int}",
            "@dataclass class(){second: int; first: int; extra: int=0}",
        ),
        ("class(Base){value: int}", "class(Other){value: int; extra: int=0}"),
        ("class(){value: int}", "class(){value: int; extra: Annotated[int, 'x=y']}"),
        (
            "@dataclass class(){value: int}",
            "@dataclass class(){value: int; extra: int=field()}",
        ),
        (
            "class(BaseModel){value: int}",
            "class(BaseModel){value: int; extra: int=Field(...)}",
        ),
        ("class(){value: int}", "class(){value: int; value(self) -> int}"),
        ("class(){value(self) -> int}", "class(){value(self) -> int; value: int=0}"),
        ("class(){}", "class(){__init__(self, value: int) -> None}"),
        ("class(UnknownBase){}", "class(UnknownBase){new_method(self) -> int}"),
        (
            "@dataclass class(Base){inherits[Base]=class(){value: int}; other: int}",
            "@dataclass class(Base){inherits[Base]=class(){value: int}; other: int; value: int=0}",
        ),
        ("class(){value: int}", "class(){value: int; malformed: int=(}"),
        (
            "def(value: str=' [annotations: old]') -> str",
            "def(value: str=' [annotations: new]', *, flag: bool=False) -> str",
        ),
        (
            "def(value: str='class(str, Enum){A=1}') -> str",
            "def(value: str='class(str, Enum){A=1; B=2}') -> str",
        ),
    ],
)
def test_AC_meta_public_boundary_8_breaking_changes_stay_blocked(
    before: str, after: str
) -> None:
    """AC-meta.public-boundary.8: structural additions never hide changed binding or required inputs."""
    result = dependency_report.evaluate_boundary_compatibility(
        {
            "changed_public_symbols": [
                {
                    "package": "demo",
                    "symbol": "Surface",
                    "before": before,
                    "after": after,
                }
            ],
            "head": {"delivery_boundaries": [], "public_symbols": []},
        },
        consumer_proofs={},
    )
    assert result["status"] == "blocked"
    assert len(result["breaking_changes"]) == 1
