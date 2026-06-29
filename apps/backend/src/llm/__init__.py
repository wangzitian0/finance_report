"""LLM provider abstraction (EPIC-023).

``src/llm`` is the single entry point for talking to language models. It is built
around three orthogonal axes (see ``common/llm/readme.md``):

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

The package ``__init__`` is intentionally import-light: it does NOT eagerly pull
in the litellm-dependent surface (``client``/``catalog``/``cost``). That keeps
``from src.llm.common import …`` litellm-free, so lightweight consumers (e.g. the
SQLAlchemy models, run in minimal tooling environments without litellm installed)
can use the contract without the heavy dependency. Import the implementations
explicitly from their submodules (``src.llm.client``, ``src.llm.catalog``, …).
"""
