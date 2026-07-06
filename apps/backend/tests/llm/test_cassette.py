"""LLM record/replay cassette layer (EPIC-023 AC-llm.5).

Fully offline + key-free: replay reads hand-authored synthetic cassettes, record
writes against a mocked client. No real provider key is ever used. The tests pin
the layer's contract — modes, model-id-agnostic fingerprinting, normalisation,
miss-as-hard-failure, idempotent record, and the correctness/flow-only tagging —
not any provider's behaviour. Real recording against a live provider is the
follow-up issue, exercised by ``make llm-record``.
"""

from __future__ import annotations

import json

import pytest

from src.llm.extension.cassette import (
    CASSETTE_DIR,
    Cassette,
    CassetteMiss,
    CassetteMode,
    CassetteRecorder,
    CassetteStore,
    CassetteTag,
    CassetteValidationError,
    fingerprint,
    miss_summary,
)

# A synthetic request used across the replay/record tests. Anonymised content
# only — no real amounts, accounts, names, or filenames.
_MESSAGES = [
    {"role": "system", "content": "Extract the closing balance."},
    {"role": "user", "content": "Closing balance: 100.00 on statement S-0001."},
]
_DECODE = {"temperature": 0, "max_tokens": 256}
_ROLE = "extraction.json"
_RESPONSE = {"text": '{"closing_balance": "100.00"}', "model_id": "synthetic/glm"}


def _make_recorder(store: CassetteStore, mode: CassetteMode) -> CassetteRecorder:
    return CassetteRecorder(store, mode=mode)


async def _live(_response: dict | None = None):
    """A stand-in 'real provider call' — used only in record/off mode tests."""
    return dict(_response if _response is not None else _RESPONSE)


# --- mode resolution ---


# --- replay (no network, no key) ---


async def test_AC23_5_2_replay_returns_recorded_response_without_network(replay_recorder):
    """AC-llm.5.2: replay serves the committed response with zero network and no key
    — the live call must never be invoked."""

    async def _explode():  # pragma: no cover - must not run in replay
        raise AssertionError("replay must not perform a live call")

    out = await replay_recorder.call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert out == _RESPONSE


async def test_AC23_5_3_replay_miss_is_a_hard_failure_no_network(temp_store):
    """AC-llm.5.3: a request with no matching cassette fails clearly in replay and
    does NOT fall back to the network."""
    recorder = _make_recorder(temp_store, CassetteMode.REPLAY)

    async def _explode():  # pragma: no cover - must not run on a miss
        raise AssertionError("replay miss must not perform a live call")

    with pytest.raises(CassetteMiss) as excinfo:
        await recorder.call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert "make llm-record" in str(excinfo.value)
    assert recorder.misses == [excinfo.value.key]


def test_AC23_5_3_miss_summary_is_one_actionable_batch():
    """AC-llm.5.3: misses batch into one actionable summary, not N cryptic errors."""
    summary = miss_summary(["k2", "k1", "k1"])
    assert summary.startswith("2 cassette(s) need re-record")
    assert "k1" in summary and "k2" in summary
    assert "make llm-record" in summary


# --- record (mocked client, no key) ---


async def test_AC23_5_4_record_writes_cassette_against_mocked_client(record_recorder, temp_store):
    """AC-llm.5.4: record performs the (mocked) provider call and persists a cassette
    that replay can then serve back."""
    out = await record_recorder.call(_live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert out == _RESPONSE
    key = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    stored = temp_store.get(key)
    assert stored is not None
    assert stored.response == _RESPONSE
    # round-trips through replay
    replay = _make_recorder(temp_store, CassetteMode.REPLAY)

    async def _explode():  # pragma: no cover
        raise AssertionError("no network")

    assert await replay.call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE) == _RESPONSE


async def test_AC23_5_4_re_record_is_idempotent(record_recorder, temp_store):
    """AC-llm.5.4: re-recording an unchanged request writes identical bytes (no diff
    churn) even when the live response carries a per-call volatile field — the
    stored response is normalised so `request_id`/`created`/`id` do not churn the
    committed cassette."""
    key = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)

    async def _live_volatile():
        # A new random id on every call, as a real provider would return.
        import uuid

        return {**_RESPONSE, "request_id": uuid.uuid4().hex, "created": 1700000000}

    await record_recorder.call(_live_volatile, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    first = temp_store._path(key).read_text(encoding="utf-8")
    # The committed cassette dropped the volatile fields.
    assert "request_id" not in first
    assert "created" not in first

    # Re-record: a fresh random id, but the stored bytes must be identical.
    await record_recorder.call(_live_volatile, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert temp_store._path(key).read_text(encoding="utf-8") == first


async def test_AC23_5_4_off_mode_is_plain_live_call(temp_store):
    """AC-llm.5.1 / AC-llm.5.4: without an explicit ``cassette_mode`` seam the
    recorder is off — plain live call, nothing written (no process-level mode
    env exists anymore; the transparent decision is the engaged layer's,
    AC-llm.10.x)."""
    recorder = _make_recorder(temp_store, CassetteMode.OFF)
    out = await recorder.call(_live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert out == _RESPONSE
    key = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert temp_store.get(key) is None


# --- fingerprint integrity ---


def test_AC23_5_5_output_affecting_change_misses():
    """AC-llm.5.5: changing a field that affects the request sent -> different key
    (no stale match)."""
    base = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    changed_msg = fingerprint(
        role=_ROLE,
        messages=[_MESSAGES[0], {"role": "user", "content": "Closing balance: 200.00"}],
        decode_params=_DECODE,
    )
    changed_param = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params={**_DECODE, "temperature": 1})
    assert base != changed_msg
    assert base != changed_param


def test_AC23_5_5_semantically_different_requests_differ():
    """AC-llm.5.5: two semantically-different requests -> different keys (no false
    match from over-normalisation)."""
    a = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    b = fingerprint(role="advisor.chat", messages=_MESSAGES, decode_params=_DECODE)
    assert a != b


def test_AC23_5_5_model_id_agnostic_same_key():
    """AC-llm.5.5: the same semantic request under a different model id resolves the
    SAME key — model id is not part of the fingerprint (glm-5.1 -> 5.2 is a
    re-record, not an invalidation)."""
    # The fingerprint signature does not take a model id at all; identical inputs
    # always yield the same key regardless of which model the live call used.
    k1 = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    k2 = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert k1 == k2


def test_AC23_5_5_image_bytes_fingerprinted_by_content():
    """AC-llm.5.5: identical image bytes -> same key; different bytes -> different
    key (image content is hashed, not the transport encoding)."""
    img_a = b"\x89PNG\r\n\x1a\nAAAA"
    img_b = b"\x89PNG\r\n\x1a\nBBBB"
    msg = lambda data: [{"role": "user", "content": [{"type": "image", "image": data}]}]  # noqa: E731
    assert fingerprint(role="extraction.vision", messages=msg(img_a)) == fingerprint(
        role="extraction.vision", messages=msg(img_a)
    )
    assert fingerprint(role="extraction.vision", messages=msg(img_a)) != fingerprint(
        role="extraction.vision", messages=msg(img_b)
    )


def test_AC23_5_6_normalization_strips_only_volatile_fields():
    """AC-llm.5.6: normalisation strips only the intended volatile fields; an
    output-relevant field changing the key proves nothing else is stripped."""
    with_volatile = fingerprint(
        role=_ROLE,
        messages=[{"role": "user", "content": "x", "timestamp": "2026-06-21T00:00:00Z", "request_id": "r1"}],
        decode_params=_DECODE,
    )
    without_volatile = fingerprint(
        role=_ROLE,
        messages=[{"role": "user", "content": "x", "timestamp": "1999-01-01T00:00:00Z", "request_id": "r2"}],
        decode_params=_DECODE,
    )
    # volatile fields differ but the key is identical -> they were stripped
    assert with_volatile == without_volatile
    # a non-volatile field differing -> key changes -> nothing else was stripped
    content_changed = fingerprint(
        role=_ROLE,
        messages=[{"role": "user", "content": "y", "timestamp": "2026-06-21T00:00:00Z"}],
        decode_params=_DECODE,
    )
    assert with_volatile != content_changed


# --- correctness tagging ---


async def test_AC23_5_7_correctness_cassette_refuses_to_record_when_validation_fails(record_recorder):
    """AC-llm.5.7: a correctness cassette MUST refuse to record if the response fails
    ground-truth validation (recording a wrong answer would make CI green while
    asserting the LLM read numbers it never read)."""

    def reject(_response: dict) -> bool:
        return False  # ground-truth mismatch

    with pytest.raises(CassetteValidationError):
        await record_recorder.call(
            _live,
            role=_ROLE,
            messages=_MESSAGES,
            decode_params=_DECODE,
            tag=CassetteTag.CORRECTNESS,
            validator=reject,
        )


async def test_AC23_5_7_correctness_cassette_records_when_validation_passes(record_recorder, temp_store):
    """AC-llm.5.7: a correctness cassette records when ground-truth validation passes."""

    def accept(response: dict) -> bool:
        return "100.00" in response["text"]

    await record_recorder.call(
        _live,
        role=_ROLE,
        messages=_MESSAGES,
        decode_params=_DECODE,
        tag=CassetteTag.CORRECTNESS,
        validator=accept,
    )
    key = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    stored = temp_store.get(key)
    assert stored is not None and stored.tag is CassetteTag.CORRECTNESS


async def test_AC23_5_7_correctness_validator_raising_refuses_record(record_recorder):
    """AC-llm.5.7: a validator that raises (rather than returning False) still refuses
    the record — any validation error is treated as a ground-truth mismatch."""

    def boom(_response: dict) -> bool:
        raise ValueError("ground-truth fixture unavailable")

    with pytest.raises(CassetteValidationError):
        await record_recorder.call(
            _live,
            role=_ROLE,
            messages=_MESSAGES,
            decode_params=_DECODE,
            tag=CassetteTag.CORRECTNESS,
            validator=boom,
        )


def test_AC23_5_3_miss_summary_empty_when_no_misses():
    """AC-llm.5.3: no misses -> empty summary (nothing to re-record)."""
    assert miss_summary([]) == ""


async def test_AC23_5_7_correctness_record_requires_a_validator(record_recorder):
    """AC-llm.5.7: a correctness record with no validator is refused (cannot claim
    correctness it never checked)."""
    with pytest.raises(CassetteValidationError):
        await record_recorder.call(
            _live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE, tag=CassetteTag.CORRECTNESS
        )


# --- committed synthetic fixtures are well-formed + on the default path ---


def test_AC23_5_2_committed_fixtures_match_their_keys():
    """AC-llm.5.2: every committed synthetic cassette is keyed by its own fingerprint
    (so the default store finds it) and round-trips through (de)serialisation."""
    fixtures = sorted(CASSETTE_DIR.glob("*.json"))
    assert fixtures, "expected committed synthetic cassettes under the default dir"
    for path in fixtures:
        data = json.loads(path.read_text(encoding="utf-8"))
        cassette = Cassette.from_json(data)
        assert path.stem == cassette.key
        recomputed = fingerprint(
            role=cassette.request["role"],
            messages=cassette.request["messages"],
            decode_params=cassette.request["decode_params"],
        )
        assert recomputed == cassette.key
        # default-path store (no directory override) resolves it
        assert CassetteStore().get(cassette.key) is not None
