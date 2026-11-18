from __future__ import annotations

import pytest

import src.llm.extension.client as client_mod
from src.llm import accumulate_stream
from src.llm.base import DecodeParams, LLMError
from src.llm.extension.cassette import CassetteMiss, CassetteMode, CassetteStore, CassetteTag, CassetteValidationError, fingerprint
from src.llm.extension.client import CassetteOptions, litellm_stream as _typed_litellm_stream
from tests.llm.conftest import StreamChunk, explode_litellm, zai_provider

_TEXT_MESSAGES = [{"role": "system", "content": "Extract transactions as JSON."}, {"role": "user", "content": "Statement S-0001 closing balance 100.00"}]
_TEXT_DECODE = {"temperature": 0.0, "max_tokens": 512}
_TEXT_FROZEN = '{"transactions": [], "closing_balance": "100.00"}'
_VISION_MESSAGES = [
    {"role": "user", "content": [{"type": "text", "text": "Read this statement image and return JSON."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"}}]}
]
_VISION_FROZEN = '{"transactions": [], "closing_balance": "250.00"}'


def _run_stream(messages, *, model_id="glm-5.1", max_tokens=None, temperature=None, store=None, mode=None, tag=CassetteTag.FLOW_ONLY, validator=None):
    return accumulate_stream(
        _typed_litellm_stream(messages, provider=zai_provider(), model_id=model_id, decode=DecodeParams(max_tokens=max_tokens, temperature=temperature), cassette=CassetteOptions(store=store, mode=mode, tag=tag, validator=validator))
    )


def _fake_stream(*pieces: str):
    async def fake_acompletion(**_kwargs):
        async def gen():
            for piece in pieces:
                yield StreamChunk(piece)

        return gen()

    return fake_acompletion


@pytest.mark.parametrize(("messages", "model_id", "max_tokens", "expected"), [(_TEXT_MESSAGES, "glm-5.1", 512, _TEXT_FROZEN), (_TEXT_MESSAGES, "glm-5.2", 512, _TEXT_FROZEN), (_VISION_MESSAGES, "test-vision-model", None, _VISION_FROZEN)])
async def test_AC23_6_1_and_5_replay_synthesises_stream(monkeypatch, committed_store, messages, model_id: str, max_tokens, expected: str) -> None:
    monkeypatch.setattr(client_mod.litellm, "acompletion", explode_litellm)
    assert await _run_stream(messages, model_id=model_id, max_tokens=max_tokens, temperature=0.0, store=committed_store, mode=CassetteMode.REPLAY) == expected
    assert (client_mod._stream_role(_VISION_MESSAGES), client_mod._stream_role(_TEXT_MESSAGES)) == ("vision", "text")
    assert fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE) != fingerprint(role="vision", messages=_VISION_MESSAGES, decode_params={"temperature": 0.0})


async def test_AC23_6_2_3_4_miss_record_and_off_modes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(client_mod.litellm, "acompletion", explode_litellm)
    with pytest.raises(CassetteMiss) as ei:
        await _run_stream([{"role": "user", "content": "no cassette for this"}], store=CassetteStore(directory=tmp_path / "empty"), mode=CassetteMode.REPLAY)
    assert ei.value.scene == "text"

    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream('{"a"', ":1", "}"))
    store = CassetteStore(directory=tmp_path / "c")
    out = await _run_stream(_TEXT_MESSAGES, temperature=0.0, max_tokens=512, store=store, mode=CassetteMode.RECORD)
    key = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    first_raw = (tmp_path / "c" / f"{key}.json").read_text(encoding="utf-8")
    await _run_stream(_TEXT_MESSAGES, temperature=0.0, max_tokens=512, store=store, mode=CassetteMode.RECORD)
    assert (out, store.get(key).response["stream_text"], store.get(key).role, (tmp_path / "c" / f"{key}.json").read_text(encoding="utf-8")) == ('{"a":1}', '{"a":1}', "text", first_raw)

    off_dir = tmp_path / "off"
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("Hel", "", "lo"))
    assert await _run_stream(_TEXT_MESSAGES, store=CassetteStore(directory=off_dir), mode=CassetteMode.OFF) == "Hello" and not list(off_dir.glob("*.json"))

    async def boom(**_kwargs):
        raise ValueError("bad request")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(LLMError):
        await _run_stream(_TEXT_MESSAGES, mode=CassetteMode.OFF)


async def test_AC23_6_3_record_correctness_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream('{"closing_balance":', ' "100.00"}'))
    store, key = CassetteStore(directory=tmp_path / "c"), fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    out = await _run_stream(_TEXT_MESSAGES, temperature=0.0, max_tokens=512, store=store, mode=CassetteMode.RECORD, tag=CassetteTag.CORRECTNESS, validator=lambda r: r["stream_text"] == '{"closing_balance": "100.00"}')
    assert out == '{"closing_balance": "100.00"}' and store.get(key) is not None


@pytest.mark.parametrize("validator", [None, lambda _r: False, lambda _r: (_ for _ in ()).throw(RuntimeError("validator blew up"))])
async def test_AC23_6_3_record_correctness_refuses_invalid(monkeypatch, tmp_path, validator) -> None:
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("wrong answer"))
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(CassetteValidationError):
        await _run_stream(_TEXT_MESSAGES, store=store, mode=CassetteMode.RECORD, tag=CassetteTag.CORRECTNESS, validator=validator)
    assert store.get(fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)) is None
