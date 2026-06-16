"""LLM provider abstraction (EPIC-023).

``src/llm`` is the single entry point for talking to language models. It is built
around three orthogonal axes (see ``docs/ssot/llm.md``):

- **Protocol family** — ``openai-compatible`` / ``anthropic-compatible`` /
  ``openrouter-compatible``. Every concrete vendor (Z.AI/GLM, DeepSeek, a local
  vLLM, …) slots into one of these three; they are *not* enumerated as special
  cases.
- **Model** — a dynamic catalogue that may be far larger than the bound set,
  each entry carrying capabilities (modalities, free-tier, pricing).
- **Scene** — the fixed, code-defined set of call sites (``extraction.ocr``,
  ``advisor.chat``, …). The binding ``scene -> model`` is the configurable
  surface.

``src/llm/common`` holds the frozen contract (types + protocols + the secret
cipher) that the litellm client implementation (EPIC A) and the DB-backed
configuration layer (EPIC B) both build against. Importing from ``common`` keeps
the two halves decoupled so they can evolve in parallel.

This top-level package re-exports the EPIC A litellm surface (client, catalogue,
cost, env config). Provider-specific routing lives in :mod:`src.llm.routing`.
"""

from __future__ import annotations

from src.llm.catalog import LitellmCatalog
from src.llm.client import LitellmClient, litellm_complete, litellm_stream
from src.llm.cost import DailyBudgetMeter
from src.llm.env_config import EnvConfigSource
from src.llm.routing import LitellmCall, build_call

__all__ = [
    "LitellmClient",
    "litellm_stream",
    "litellm_complete",
    "LitellmCatalog",
    "DailyBudgetMeter",
    "EnvConfigSource",
    "LitellmCall",
    "build_call",
]
