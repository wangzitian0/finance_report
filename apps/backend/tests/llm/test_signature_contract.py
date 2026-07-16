"""Signature-surgery contracts for issue #1866 PR-C."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src import advisor
from src.llm import (
    ChatResult,
    DecodeParams,
    LitellmClient,
    LLMClient,
    Scene,
    Usage,
    estimate_tokens,
    litellm_stream,
)

BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"


def _function_definitions(package: str, name: str) -> list[Path]:
    definitions = []
    for path in (BACKEND_SRC / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in ast.walk(tree)
        ):
            definitions.append(path)
    return definitions


async def test_AC_llm_typed_client_1_scene_client_is_implemented_and_consumed(monkeypatch) -> None:
    """AC-llm.typed-client.1: the protocol is real and advisor uses its scene seam."""
    from src.llm import ReasoningEffort, SceneBinding
    from src.llm.extension import scene_client

    class _Config:
        calls = 0

        async def get_binding(self, scene):
            self.calls += 1
            return SceneBinding(
                scene=scene,
                model_id="provider/model",
                reasoning=ReasoningEffort.HIGH,
                max_tokens=321,
            )

    seen: dict[str, object] = {}

    async def fake_stream(messages, model_id, **kwargs):
        seen.update(messages=messages, model_id=model_id, **kwargs)
        yield "typed"

    monkeypatch.setattr(scene_client, "_stream_ai_base", fake_stream)
    config = _Config()
    client = LitellmClient(user_id=None, config_source=config)

    assert isinstance(client, LLMClient)
    assert [chunk async for chunk in client.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}])] == [
        "typed"
    ]
    assert seen["model_id"] == "provider/model"
    assert seen["decode"] == DecodeParams(max_tokens=321, reasoning=ReasoningEffort.HIGH)
    assert await client.complete(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]) == ChatResult(
        text="typed",
        model_id="provider/model",
        usage=Usage(prompt_tokens=1, completion_tokens=1),
    )
    assert config.calls == 2
    source = (BACKEND_SRC / "advisor" / "extension" / "service.py").read_text(encoding="utf-8")
    assert "get_llm_client" in source
    assert "Scene.ADVISOR_CHAT" in source


def test_AC_llm_decode_contract_1_groups_decode_and_decorates_cassettes() -> None:
    """AC-llm.decode-contract.1: one value carries decode knobs; cassette is a wrapper."""
    decode = DecodeParams(max_tokens=512, temperature=0, seed=7)
    parameters = inspect.signature(litellm_stream).parameters

    assert decode.as_request() == {"max_tokens": 512, "temperature": 0, "seed": 7}
    assert "decode" in parameters
    assert not {"max_tokens", "temperature", "reasoning", "seed", "extra_body"} & parameters.keys()
    assert getattr(litellm_stream, "__cassette_decorated__", False) is True


def test_AC_llm_token_estimate_1_is_single_homed() -> None:
    """AC-llm.token-estimate.1: llm owns the only definition and advisor only consumes."""
    definitions = _function_definitions("llm", "estimate_tokens") + _function_definitions("advisor", "estimate_tokens")

    assert definitions == [BACKEND_SRC / "llm" / "base" / "usage.py"]
    assert estimate_tokens("") == 0
    assert "estimate_tokens" not in advisor.__all__
