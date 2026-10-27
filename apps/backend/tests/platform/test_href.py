"""AC-platform.1.6: one internal action href check serves the reporting and workflow schemas."""

import pytest
from pydantic import ValidationError

import src.schemas.reporting as reporting_schemas
import src.workflow.base.types as workflow_types
from src.platform import validate_internal_action_href

MESSAGE = "action_href must be an internal relative path"
EXTERNAL = ["https://external.example.com", "//protocol-relative.com", "relative/path", "javascript://alert(1)"]


@pytest.mark.parametrize("href", ["/reports/balance-sheet", "/api/v1/export?format=csv"])
def test_AC_platform_1_6_internal_href_passes_unchanged(href):
    assert validate_internal_action_href(href) == href


@pytest.mark.parametrize("href", EXTERNAL)
def test_AC_platform_1_6_external_href_is_rejected_by_both_schemas(href):
    blocker = {"code": "c", "label": "l", "severity": "warning", "count": 1, "reason": "r"}
    event = {"family": "source.uploaded", "severity": "info", "title": "t", "summary": "s", "source_type": "statement"}
    event |= {"source_id": "00000000-0000-0000-0000-000000000001", "report_impact": "none", "dedupe_key": "k"}
    with pytest.raises(ValueError, match=MESSAGE):
        validate_internal_action_href(href)
    with pytest.raises(ValidationError, match=MESSAGE):
        reporting_schemas.PersonalReportPackageReadinessBlocker(**blocker, action_href=href)
    with pytest.raises(ValidationError, match=MESSAGE):
        workflow_types.WorkflowEventCreate.model_validate(event | {"action_href": href})


def test_AC_platform_1_6_reporting_and_workflow_schemas_use_the_platform_check():
    """Both schemas bind the platform function itself; a private copy fails this identity check."""
    assert reporting_schemas.validate_internal_action_href is validate_internal_action_href
    assert workflow_types.validate_internal_action_href is validate_internal_action_href
    assert not hasattr(reporting_schemas, "_validate_internal_action_href")
    assert not hasattr(workflow_types, "_validate_internal_action_href")
