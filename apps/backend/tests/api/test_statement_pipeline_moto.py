"""#1520 / AC-runtime.8.1 — the REAL upload→S3→load→parse pipeline in the fast path.

Unlike the `DummyStorage` unit tests (which stay — they cover router edge cases
cheaply), this test runs the **real `StorageService` and real boto3 calls**
against moto's in-memory S3 (`mock_aws`): no wrapper stub, no MinIO container,
no network. The uploaded bytes make a functional round-trip (stored == read
back), and the loaded-back statement text is parsed through the real
`stream_ai_json` transport replaying a committed REAL-GLM cassette, asserting
the output equals the committed `text_statement_expected.json`.

Issue #1520 ACs: real StorageService through /statements/upload (AC-1), byte
round-trip (AC-2), cassette parse == expected fixture (AC-3), fast path — no
service container (AC-4), breaking the upload/get wiring fails here (AC-5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from moto import mock_aws

import src.routers.statements as statements_router
from src.routers.statements import build_statement_storage_key
from src.services.ai_streaming import accumulate_stream, stream_ai_json
from src.services.storage import StorageService
from tests.extraction.test_extraction_cassette_replay import (
    _TEXT_MAX_TOKENS,
    _TEXT_MODEL,
    _TEXT_PROMPT,
    _TEXT_STATEMENT,
    _loads_tolerant,
)

pytestmark = pytest.mark.asyncio

_EXPECTED = Path(__file__).resolve().parents[1] / "fixtures" / "generated" / "text_statement_expected.json"


@pytest.fixture
def moto_s3(monkeypatch: pytest.MonkeyPatch):
    """In-memory S3 through the real boto3 client (issue #1520: NOT MinIO,
    NOT a DummyStorage). moto intercepts the default AWS endpoint only, so the
    MinIO endpoint override is cleared — the real client/signing/round-trip
    code still runs. Clears the class-level ensure-bucket cache so the real
    `_ensure_bucket` executes against the moto backend."""
    from src.config import settings

    monkeypatch.setattr(settings, "s3_endpoint", None)
    original_cache = StorageService._checked_buckets
    with mock_aws():
        StorageService._checked_buckets = set()
        yield
    StorageService._checked_buckets = original_cache


@pytest.fixture
def no_async_parse(monkeypatch: pytest.MonkeyPatch):
    """Detach the async parse worker — the pipeline's parse step is exercised
    synchronously below via the cassette (the storage seam stays REAL)."""

    async def _no_parse(**_kwargs):
        return None

    monkeypatch.setattr(statements_router, "submit_parse_pipeline", _no_parse)


async def test_AC_1520_upload_s3_load_parse_pipeline(
    client: AsyncClient, moto_s3, no_async_parse, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _TEXT_STATEMENT.encode("utf-8")

    # 1. Upload through the real route → real StorageService.upload_bytes → moto S3.
    response = await client.post(
        "/statements/upload",
        files={"file": ("statement.csv", content, "text/csv")},
        data={"institution": "DBS"},
    )
    assert response.status_code == 202, response.text
    statement = response.json()

    # 2. Functional round-trip: the real get_object returns byte-identical content.
    storage_key = build_statement_storage_key(
        statement_id=statement["id"],
        file_hash=hashlib.sha256(content).hexdigest(),
        extension="csv",
    )
    loaded = StorageService().get_object(storage_key)
    assert loaded == content, "stored bytes != read-back bytes (storage round-trip broken)"

    # 3. Parse the LOADED-BACK text via the real streaming transport replaying a
    #    committed REAL-GLM cassette (no key, no network), and assert the result
    #    equals the committed expected fixture.
    monkeypatch.setenv("LLM_CASSETTE_MODE", "replay")
    messages = [{"role": "user", "content": _TEXT_PROMPT + "\n\n" + loaded.decode("utf-8")}]
    stream = stream_ai_json(
        messages=messages,
        model=_TEXT_MODEL,
        max_tokens=_TEXT_MAX_TOKENS,
        temperature=0.0,
        thinking={"type": "disabled"},
    )
    parsed = _loads_tolerant(await accumulate_stream(stream))
    expected = json.loads(_EXPECTED.read_text(encoding="utf-8"))
    assert parsed == expected


async def test_AC_1520_round_trip_uses_the_real_client(client: AsyncClient, moto_s3, no_async_parse) -> None:
    """AC-5 interception proof: the object genuinely exists in the S3 backend
    under the derived key — a wiring break (upload skipped / wrong key) fails."""
    content = b"opening 1\nclosing 2\n"
    response = await client.post(
        "/statements/upload",
        files={"file": ("statement.csv", content, "text/csv")},
        data={"institution": "DBS"},
    )
    assert response.status_code == 202, response.text

    service = StorageService()
    listed = service.client.list_objects_v2(Bucket=service.bucket)
    keys = [obj["Key"] for obj in listed.get("Contents", [])]
    assert len(keys) == 1 and keys[0].endswith(".csv")
    assert service.get_object(keys[0]) == content
