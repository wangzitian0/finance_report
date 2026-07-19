"""Thin pytest lifecycle adapter for scenario-bound executed proofs."""

from __future__ import annotations

from typing import Any

import pytest

from common.testing.executed_proof import record_executed_proof


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item: Any, call: Any):
    """Record proof metadata only after pytest has resolved the call result."""
    outcome = yield
    record_executed_proof(item, outcome.get_result())
