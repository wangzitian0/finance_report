from __future__ import annotations

import json
import uuid

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
    layer_engaged,
    miss_summary,
)

_MESSAGES = [{"role": "system", "content": "Extract the closing balance."}, {"role": "user", "content": "Closing balance: 100.00 on statement S-0001."}]
_DECODE = {"temperature": 0, "max_tokens": 256}
_ROLE = "extraction.json"
_RESPONSE = {"text": '{"closing_balance": "100.00"}', "model_id": "synthetic/glm"}


async def _live(_response: dict | None = None):
    return dict(_response if _response is not None else _RESPONSE)


async def test_AC23_5_2_3_4_replay_miss_record_and_off(replay_recorder, record_recorder, temp_store, tmp_path) -> None:
    assert layer_engaged(), "cassette layer must be engaged by tests/conftest.py"

    async def _explode():
        raise AssertionError("replay must not perform a live call")

    assert await replay_recorder.call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE) == _RESPONSE
    miss_rec = CassetteRecorder(temp_store, mode=CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss) as excinfo:
        await miss_rec.call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert "make llm-record" in str(excinfo.value) and miss_rec.misses == [excinfo.value.key]

    summary = miss_summary(["k2", "k1", "k1"])
    assert summary.startswith("2 cassette(s) need re-record") and "k1" in summary and "k2" in summary and "make llm-record" in summary and miss_summary([]) == ""

    async def _live_volatile():
        return {**_RESPONSE, "request_id": uuid.uuid4().hex, "created": 1700000000}

    key = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    await record_recorder.call(_live_volatile, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    first = temp_store._path(key).read_text(encoding="utf-8")
    await record_recorder.call(_live_volatile, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert "request_id" not in first and "created" not in first and temp_store._path(key).read_text(encoding="utf-8") == first
    assert await CassetteRecorder(temp_store, mode=CassetteMode.REPLAY).call(_explode, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE) == _RESPONSE

    off_store = CassetteStore(directory=tmp_path / "off")
    assert await CassetteRecorder(off_store, mode=CassetteMode.OFF).call(_live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE) == _RESPONSE and off_store.get(key) is None


def test_AC23_5_5_and_6_fingerprint_normalization_and_committed_fixtures() -> None:
    base = fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    img_msg = lambda data: [{"role": "user", "content": [{"type": "image", "image": data}]}]
    assert base == fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE)
    assert len({base, fingerprint(role=_ROLE, messages=[_MESSAGES[0], {"role": "user", "content": "Closing balance: 200.00"}], decode_params=_DECODE), fingerprint(role=_ROLE, messages=_MESSAGES, decode_params={**_DECODE, "temperature": 1}), fingerprint(role="advisor.chat", messages=_MESSAGES, decode_params=_DECODE)}) == 4
    assert fingerprint(role="extraction.vision", messages=img_msg(b"\x89PNG\r\n\x1a\nAAAA")) != fingerprint(role="extraction.vision", messages=img_msg(b"\x89PNG\r\n\x1a\nBBBB"))

    w_vol = fingerprint(role=_ROLE, messages=[{"role": "user", "content": "x", "timestamp": "2026-06-21T00:00:00Z", "request_id": "r1"}], decode_params=_DECODE)
    assert w_vol == fingerprint(role=_ROLE, messages=[{"role": "user", "content": "x", "timestamp": "1999-01-01T00:00:00Z", "request_id": "r2"}], decode_params=_DECODE)
    assert w_vol != fingerprint(role=_ROLE, messages=[{"role": "user", "content": "y", "timestamp": "2026-06-21T00:00:00Z"}], decode_params=_DECODE)

    fixtures = sorted(CASSETTE_DIR.glob("*.json"))
    assert fixtures
    for path in fixtures:
        c = Cassette.from_json(json.loads(path.read_text(encoding="utf-8")))
        assert path.stem == c.key == fingerprint(role=c.request["role"], messages=c.request["messages"], decode_params=c.request["decode_params"]) and CassetteStore().get(c.key) is not None


@pytest.mark.parametrize(("validator", "should_pass"), [(lambda r: "100.00" in r["text"], True), (None, False), (lambda _r: False, False), (lambda _r: (_ for _ in ()).throw(ValueError("ground-truth fixture unavailable")), False)])
async def test_AC23_5_7_correctness_cassette_validation(record_recorder, temp_store, validator, should_pass: bool) -> None:
    if should_pass:
        await record_recorder.call(_live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE, tag=CassetteTag.CORRECTNESS, validator=validator)
        stored = temp_store.get(fingerprint(role=_ROLE, messages=_MESSAGES, decode_params=_DECODE))
        assert stored is not None and stored.tag is CassetteTag.CORRECTNESS
    else:
        with pytest.raises(CassetteValidationError):
            await record_recorder.call(_live, role=_ROLE, messages=_MESSAGES, decode_params=_DECODE, tag=CassetteTag.CORRECTNESS, validator=validator)
