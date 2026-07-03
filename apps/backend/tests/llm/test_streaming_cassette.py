"""Streaming-cassette bridge for ``litellm_stream`` (EPIC-023 AC-llm.6).

The real extraction transport is STREAMING and previously bypassed the cassette
layer entirely, so PR CI never exercised the LLM path. These tests pin the
bridge that routes ``litellm_stream`` through record/replay while preserving
streaming for the caller — all fully offline and key-free:

- ``off`` passes the live (mocked) stream through byte-for-byte (keeps prod /
  staging ``-m llm`` live and real);
- ``replay`` synthesises a stream from a committed hand-authored frozen-text
  cassette with ZERO network and NO API key, and a miss is a hard ``CassetteMiss``;
- ``record`` accumulates the (mocked) live stream and freezes a cassette
  idempotently;
- the fingerprint role is derived from the messages (image part -> ``vision``,
  text-only -> ``text``), the two get different keys, and a model-id swap keeps
  the key (model-id-agnostic).

They assert provider-agnostic response *handling*, never provider-specific
correctness (that stays the staging ``-m llm`` gate's job). The synthetic
cassettes under ``common/testing/fixtures/llm_cassettes`` carry only anonymised
content.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.llm.extension.client as client_mod
from src.llm.base import LLMError, ProtocolFamily, ProviderRef
from src.llm.extension.cassette import (
    CassetteMiss,
    CassetteMode,
    CassetteStore,
    CassetteTag,
    fingerprint,
)
from src.llm.extension.client import litellm_stream
from src.services.ai_streaming import accumulate_stream

FIXTURE_CASSETTE_DIR = Path(__file__).resolve().parents[4] / "common" / "testing" / "fixtures" / "llm_cassettes"

# Mirror the committed synthetic cassettes (authored under FIXTURE_CASSETTE_DIR);
# the fingerprint of these inputs resolves those frozen-text files in replay.
_TEXT_MESSAGES = [
    {"role": "system", "content": "Extract transactions as JSON."},
    {"role": "user", "content": "Statement S-0001 closing balance 100.00"},
]
_TEXT_DECODE = {"temperature": 0.0, "max_tokens": 512}
_TEXT_FROZEN = '{"transactions": [], "closing_balance": "100.00"}'

_VISION_MESSAGES = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Read this statement image and return JSON."},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
                },
            },
        ],
    },
]
_VISION_DECODE = {"temperature": 0.0}
_VISION_FROZEN = '{"transactions": [], "closing_balance": "250.00"}'


def _provider() -> ProviderRef:
    return ProviderRef(
        id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://api.z.ai"
    )


class _Delta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [_Choice(content)]


def _fake_stream(*pieces: str):
    """A litellm.acompletion stand-in that yields the given chunks."""

    async def fake_acompletion(**kwargs):
        async def gen():
            for piece in pieces:
                yield _Chunk(piece)

        return gen()

    return fake_acompletion


@pytest.fixture
def committed_store() -> CassetteStore:
    return CassetteStore(directory=FIXTURE_CASSETTE_DIR)


# --- replay: synthesise a stream from a frozen-text cassette (zero key/network) ---


async def test_AC23_6_1_replay_synthesises_stream_from_frozen_text_cassette(monkeypatch, committed_store):
    """AC-llm.6.1: replay reads the committed frozen-text cassette and synthesises a
    stream; accumulate_stream rebuilds the recorded text with NO network/key."""

    async def explode(**kwargs):  # pragma: no cover - replay must not touch litellm
        raise AssertionError("replay must not call litellm")

    monkeypatch.setattr(client_mod.litellm, "acompletion", explode)
    chunks = [
        c
        async for c in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=committed_store,
            cassette_mode=CassetteMode.REPLAY,
        )
    ]
    assert "".join(chunks) == _TEXT_FROZEN
    # The service-level accumulator the extraction pipeline uses sees the same text.
    again = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=committed_store,
            cassette_mode=CassetteMode.REPLAY,
        )
    )
    assert again == _TEXT_FROZEN


async def test_AC23_6_1_replay_vision_cassette_synthesises_stream(monkeypatch, committed_store):
    """AC-llm.6.1: a vision (image-part) request resolves the committed vision
    cassette in replay — the same bridge serves default-config OCR/vision."""

    async def explode(**kwargs):  # pragma: no cover
        raise AssertionError("replay must not call litellm")

    monkeypatch.setattr(client_mod.litellm, "acompletion", explode)
    text = await accumulate_stream(
        litellm_stream(
            _VISION_MESSAGES,
            provider=_provider(),
            model_id="glm-4.6V",
            temperature=0.0,
            cassette_store=committed_store,
            cassette_mode=CassetteMode.REPLAY,
        )
    )
    assert text == _VISION_FROZEN


async def test_AC23_6_2_replay_miss_is_hard_failure(monkeypatch, tmp_path):
    """AC-llm.6.2 / AC-runtime.5.1 (#1581): a request with no matching cassette is
    a hard CassetteMiss in replay — never a network fallback (the live call is
    never made). Because the fingerprint is input-keyed (sha256 of role + messages
    + decode params), a changed input IS a miss: runtime invariant 5."""

    async def explode(**kwargs):  # pragma: no cover
        raise AssertionError("replay must not call litellm")

    monkeypatch.setattr(client_mod.litellm, "acompletion", explode)
    empty_store = CassetteStore(directory=tmp_path / "empty")
    with pytest.raises(CassetteMiss) as ei:
        async for _ in litellm_stream(
            [{"role": "user", "content": "no cassette for this"}],
            provider=_provider(),
            model_id="glm-5.1",
            cassette_store=empty_store,
            cassette_mode=CassetteMode.REPLAY,
        ):
            pass
    assert ei.value.scene == "text"


# --- record: accumulate the live (mocked) stream + freeze idempotently ---


async def test_AC23_6_3_record_accumulates_and_writes_cassette(monkeypatch, tmp_path):
    """AC-llm.6.3: record performs the (mocked) streaming call, accumulates the full
    text, writes a cassette, and yields the text so the caller still works."""
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream('{"a"', ":1", "}"))
    store = CassetteStore(directory=tmp_path / "c")
    out = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=store,
            cassette_mode=CassetteMode.RECORD,
        )
    )
    assert out == '{"a":1}'
    key = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    cassette = store.get(key)
    assert cassette is not None
    assert cassette.response["stream_text"] == '{"a":1}'
    assert cassette.role == "text"


async def test_AC23_6_3_record_is_idempotent(monkeypatch, tmp_path):
    """AC-llm.6.3: re-recording the same streamed request rewrites identical bytes
    (no diff churn) — the second put reports no change."""
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("frozen"))
    store = CassetteStore(directory=tmp_path / "c")
    key = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)

    async def record_once():
        await accumulate_stream(
            litellm_stream(
                _TEXT_MESSAGES,
                provider=_provider(),
                model_id="glm-5.1",
                temperature=0.0,
                max_tokens=512,
                cassette_store=store,
                cassette_mode=CassetteMode.RECORD,
            )
        )

    await record_once()
    first = store.get(key)
    first_path = (tmp_path / "c" / f"{key}.json").read_text(encoding="utf-8")
    await record_once()
    assert (tmp_path / "c" / f"{key}.json").read_text(encoding="utf-8") == first_path
    assert first is not None


# --- off: passthrough, untouched, no cassette involvement ---


async def test_AC23_6_4_off_mode_passes_stream_through_untouched(monkeypatch, tmp_path):
    """AC-llm.6.4: off mode streams the live (mocked) deltas through unchanged,
    skipping empty chunks, and writes NO cassette — prod/staging stay live."""
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("Hel", "", "lo"))
    store = CassetteStore(directory=tmp_path / "c")
    chunks = [
        c
        async for c in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            cassette_store=store,
            cassette_mode=CassetteMode.OFF,
        )
    ]
    # Deltas arrive as separate chunks (not collapsed to one) — true passthrough.
    assert chunks == ["Hel", "lo"]
    # No cassette written in off mode.
    assert not (tmp_path / "c").exists() or list((tmp_path / "c").glob("*.json")) == []


async def test_AC23_6_4_off_mode_normalises_provider_error(monkeypatch):
    """AC-llm.6.4: off mode preserves the prior error contract — a provider failure
    is normalised to LLMError exactly as before the bridge."""

    async def boom(**kwargs):
        raise ValueError("bad request")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(LLMError):
        async for _ in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            cassette_mode=CassetteMode.OFF,
        ):
            pass


# --- role derivation + model-id-agnostic keying ---


def test_AC23_6_5_role_derivation_text_vs_vision_distinct_keys():
    """AC-llm.6.5: image-part messages key as 'vision', text-only as 'text', and the
    two produce DIFFERENT fingerprints (no cross-modality false match)."""
    assert client_mod._stream_role(_VISION_MESSAGES) == "vision"
    assert client_mod._stream_role(_TEXT_MESSAGES) == "text"
    k_text = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    k_vision = fingerprint(role="vision", messages=_VISION_MESSAGES, decode_params=_VISION_DECODE)
    assert k_text != k_vision


async def test_AC23_6_5_model_id_swap_resolves_same_cassette(monkeypatch, committed_store):
    """AC-llm.6.5: swapping the model id (glm-5.1 -> glm-5.2) resolves the SAME
    committed cassette in replay — the key is model-id-agnostic."""

    async def explode(**kwargs):  # pragma: no cover
        raise AssertionError("replay must not call litellm")

    monkeypatch.setattr(client_mod.litellm, "acompletion", explode)
    out_a = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=committed_store,
            cassette_mode=CassetteMode.REPLAY,
        )
    )
    out_b = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.2",
            temperature=0.0,
            max_tokens=512,
            cassette_store=committed_store,
            cassette_mode=CassetteMode.REPLAY,
        )
    )
    assert out_a == out_b == _TEXT_FROZEN


async def test_AC23_6_3_record_correctness_requires_validator(monkeypatch, tmp_path):
    """AC-llm.6.3: a correctness streaming cassette refuses to record without a
    ground-truth validator (freezing an unvalidated answer is the trap)."""
    from src.llm.extension.cassette import CassetteValidationError

    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("anything"))
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            cassette_store=store,
            cassette_mode=CassetteMode.RECORD,
            cassette_tag=CassetteTag.CORRECTNESS,
        ):
            pass


async def test_AC23_6_3_record_correctness_validated_freezes_text(monkeypatch, tmp_path):
    """AC-llm.6.3: a correctness streaming cassette whose accumulated text passes the
    ground-truth validator records and freezes the validated text."""
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream('{"closing_balance":', ' "100.00"}'))
    store = CassetteStore(directory=tmp_path / "c")

    def validator(response: dict) -> bool:
        return response["stream_text"] == '{"closing_balance": "100.00"}'

    out = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=store,
            cassette_mode=CassetteMode.RECORD,
            cassette_tag=CassetteTag.CORRECTNESS,
            cassette_validator=validator,
        )
    )
    assert out == '{"closing_balance": "100.00"}'
    key = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    assert store.get(key) is not None


async def test_AC23_6_3_record_correctness_refuses_wrong_answer(monkeypatch, tmp_path):
    """AC-llm.6.3: a correctness cassette refuses to record (CassetteValidationError)
    when the accumulated text fails ground-truth validation — never freezes a
    wrong answer — and writes nothing."""
    from src.llm.extension.cassette import CassetteValidationError

    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("wrong answer"))
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            cassette_store=store,
            cassette_mode=CassetteMode.RECORD,
            cassette_tag=CassetteTag.CORRECTNESS,
            cassette_validator=lambda _response: False,
        ):
            pass
    key = fingerprint(role="text", messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    assert store.get(key) is None


async def test_AC23_6_3_record_correctness_validator_error_refuses(monkeypatch, tmp_path):
    """AC-llm.6.3: a validator that RAISES refuses the record (wrapped as
    CassetteValidationError), not silently freezing the response."""
    from src.llm.extension.cassette import CassetteValidationError

    def boom(_response: dict) -> bool:
        raise RuntimeError("validator blew up")

    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("anything"))
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            cassette_store=store,
            cassette_mode=CassetteMode.RECORD,
            cassette_tag=CassetteTag.CORRECTNESS,
            cassette_validator=boom,
        ):
            pass


async def test_AC23_6_3_record_default_mode_from_env(monkeypatch, tmp_path):
    """AC-llm.6.3: with no explicit cassette_mode, the bridge reads LLM_CASSETTE_MODE
    (here 'record') so the CI replay step / make llm-record drive it via the env."""
    monkeypatch.setenv("LLM_CASSETTE_MODE", "record")
    monkeypatch.setattr(client_mod.litellm, "acompletion", _fake_stream("env-driven"))
    store = CassetteStore(directory=tmp_path / "c")
    out = await accumulate_stream(
        litellm_stream(
            _TEXT_MESSAGES,
            provider=_provider(),
            model_id="glm-5.1",
            temperature=0.0,
            max_tokens=512,
            cassette_store=store,
            cassette_mode=None,
        )
    )
    assert out == "env-driven"
