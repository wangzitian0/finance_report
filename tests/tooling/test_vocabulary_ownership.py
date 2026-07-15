"""Package vocabulary ownership locks for #1865 PR-B."""

from __future__ import annotations

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _defined_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _imported_names(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def _assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _assert_owned_and_reexported(
    *,
    names: set[str],
    owner: str,
    compatibility_module: str,
    owner_module: str,
) -> None:
    owner_path = REPO / owner
    compatibility_path = REPO / compatibility_module
    assert owner_path.is_file()
    assert names <= _defined_classes(owner_path)
    assert names.isdisjoint(_defined_classes(compatibility_path))
    assert names <= _imported_names(compatibility_path, owner_module)


def test_AC_reporting_vocabulary_ownership_1_reporting_owns_wire_enums() -> None:
    """AC-reporting.vocabulary-ownership.1: reporting owns its base enums."""
    _assert_owned_and_reexported(
        names={
            "PersonalReportingFrameworkId",
            "PolicyDimension",
            "ReportLineId",
        },
        owner="apps/backend/src/reporting/base/types.py",
        compatibility_module="apps/backend/src/schemas/reporting.py",
        owner_module="src.reporting.base.types",
    )


def test_AC_platform_vocabulary_ownership_1_platform_owns_workflow_payloads() -> None:
    """AC-platform.vocabulary-ownership.1: platform owns workflow payloads."""
    _assert_owned_and_reexported(
        names={
            "WorkflowEventCountsResponse",
            "WorkflowEventCreate",
            "WorkflowEventFamily",
            "WorkflowEventListResponse",
            "WorkflowEventResponse",
            "WorkflowEventSeverity",
            "WorkflowEventStatus",
            "WorkflowEventStatusUpdate",
            "WorkflowNextActionResponse",
            "WorkflowNextActionType",
            "WorkflowPrimaryState",
            "WorkflowReportImpact",
            "WorkflowReportReadinessResponse",
            "WorkflowReportReadinessState",
            "WorkflowSessionStatus",
            "WorkflowSessionSummaryResponse",
            "WorkflowStatusResponse",
        },
        owner="apps/backend/src/platform/base/workflow.py",
        compatibility_module="apps/backend/src/schemas/workflow.py",
        owner_module="src.platform.base.workflow",
    )


def test_AC_identity_vocabulary_ownership_1_identity_owns_user_dtos() -> None:
    """AC-identity.vocabulary-ownership.1: identity owns its user DTOs."""
    _assert_owned_and_reexported(
        names={
            "UserAiSettingsResponse",
            "UserAiSettingsUpdate",
            "UserBase",
            "UserCreate",
            "UserResponse",
            "UserUpdate",
        },
        owner="apps/backend/src/identity/base/types/user.py",
        compatibility_module="apps/backend/src/schemas/user.py",
        owner_module="src.identity.base.types.user",
    )

    assert "UserListResponse" not in _defined_classes(
        REPO / "apps/backend/src/identity/base/types/user.py"
    )
    assert "UserListResponse" in _assigned_names(
        REPO / "apps/backend/src/schemas/user.py"
    )
