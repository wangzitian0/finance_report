from __future__ import annotations

from pathlib import Path

import pytest

from src.llm.base import ProtocolFamily, ProviderRef
from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore

FIXTURE_CASSETTE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "llm_cassettes"


class StreamChunk:
    def __init__(self, content: str | None) -> None:
        delta = type("_Delta", (), {"content": content})()
        self.choices = [type("_Choice", (), {"delta": delta, "message": delta, "finish_reason": None})()]


def zai_provider() -> ProviderRef:
    return ProviderRef(
        id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://api.z.ai"
    )


async def explode_litellm(**_kwargs):
    raise AssertionError("replay must not call litellm")


@pytest.fixture
def committed_store() -> CassetteStore:
    return CassetteStore(directory=FIXTURE_CASSETTE_DIR)


@pytest.fixture
def temp_store(tmp_path) -> CassetteStore:
    return CassetteStore(directory=tmp_path / "llm_cassettes")


@pytest.fixture
def replay_recorder(committed_store: CassetteStore) -> CassetteRecorder:
    return CassetteRecorder(committed_store, mode=CassetteMode.REPLAY)


@pytest.fixture
def record_recorder(temp_store: CassetteStore) -> CassetteRecorder:
    return CassetteRecorder(temp_store, mode=CassetteMode.RECORD)
