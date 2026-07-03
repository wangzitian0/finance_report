"""Extraction threads the user's id to the transport (EPIC-023 AC-llm.4.5).

So a BYO-provider user's uploads resolve their own provider instead of the
deployment/env default. ``stream_ai_json`` is mocked to capture the ``user_id``.
"""

from __future__ import annotations

import contextlib
from uuid import uuid4

import pytest

from src.extraction.extension import service as extraction_mod
from src.extraction.extension.service import ExtractionService

pytestmark = pytest.mark.no_db


async def test_AC23_4_5_extraction_threads_user_id_to_stream() -> None:
    captured: dict[str, object] = {}

    async def fake_stream_ai_json(messages, model, *, user_id=None, **_kw):
        captured["user_id"] = user_id
        yield '{"transactions": [], "institution": "X"}'

    # Patch the symbol the extraction module bound at import time.
    original = extraction_mod.stream_ai_json
    extraction_mod.stream_ai_json = fake_stream_ai_json
    try:
        service = ExtractionService()
        uid = uuid4()
        # Downstream JSON validation isn't under test; we only assert user_id was threaded.
        with contextlib.suppress(Exception):
            await service._extract_json_with_models(
                messages=[{"role": "user", "content": "x"}],
                models=["glm-4.6"],
                prompt="p",
                institution="X",
                file_type="pdf",
                return_raw=False,
                has_content=True,
                has_url=False,
                user_id=uid,
            )
    finally:
        extraction_mod.stream_ai_json = original

    assert captured.get("user_id") == uid
