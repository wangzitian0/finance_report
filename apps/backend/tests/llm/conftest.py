"""Fixtures for the LLM cassette layer tests (EPIC-023 AC23.5.1–AC23.5.7).

Support file for ``test_cassette.py`` (which carries the per-AC references
AC23.5.1 .. AC23.5.7). These run fully offline: replay reads committed JSON,
record writes against a *mocked* client (no real provider key, no network). The
synthetic cassettes used here live in ``common/testing/fixtures/llm_cassettes``
and carry only generated/anonymised content (no real amounts, accounts, names, or
filenames).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.llm.cassette import CassetteMode, CassetteRecorder, CassetteStore

FIXTURE_CASSETTE_DIR = Path(__file__).resolve().parents[4] / "common" / "testing" / "fixtures" / "llm_cassettes"


@pytest.fixture
def committed_store() -> CassetteStore:
    """A store pointed at the committed synthetic cassettes (read-only in tests)."""
    return CassetteStore(directory=FIXTURE_CASSETTE_DIR)


@pytest.fixture
def temp_store(tmp_path) -> CassetteStore:
    """A throwaway store so record-mode tests never touch committed fixtures."""
    return CassetteStore(directory=tmp_path / "llm_cassettes")


@pytest.fixture
def replay_recorder(committed_store: CassetteStore) -> CassetteRecorder:
    return CassetteRecorder(committed_store, mode=CassetteMode.REPLAY)


@pytest.fixture
def record_recorder(temp_store: CassetteStore) -> CassetteRecorder:
    return CassetteRecorder(temp_store, mode=CassetteMode.RECORD)
