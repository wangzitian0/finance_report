'AC-llm.5.1 AC-llm.5.7 EPIC-023'; from __future__ import annotations; from pathlib import Path; import pytest; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; FIXTURE_CASSETTE_DIR = Path(__file__).resolve().parents[4] / 'common' / 'testing' / 'fixtures' / 'llm_cassettes'
@pytest.fixture
def committed_store() -> CassetteStore: return CassetteStore(directory=FIXTURE_CASSETTE_DIR)
@pytest.fixture
def temp_store(tmp_path) -> CassetteStore: return CassetteStore(directory=tmp_path / 'llm_cassettes')
@pytest.fixture
def replay_recorder(committed_store: CassetteStore) -> CassetteRecorder: return CassetteRecorder(committed_store, mode=CassetteMode.REPLAY)
@pytest.fixture
def record_recorder(temp_store: CassetteStore) -> CassetteRecorder: return CassetteRecorder(temp_store, mode=CassetteMode.RECORD)
