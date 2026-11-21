# `llm` — Provider Abstraction SSOT

> **SSOT Key**: `llm_provider_abstraction` | Implementation: `apps/backend/src/llm/`.

Owns the `LLMClient` protocol (`LitellmClient`, `DecodeParams`, `estimate_tokens`), Fernet/MultiFernet at-rest encryption (`LLM_ENCRYPTION_KEYS`, `SecretCipher.rotate()`), and deterministic CI record/replay cassettes.

## <a id="axes"></a>The Three Axes

1. **Protocol family**: `openai-compatible` (OpenAI, Z.AI/GLM `glm-5.3-flash`, DeepSeek, vLLM), `anthropic-compatible`, `openrouter-compatible`, `google-gemini`.
2. **Model**: Dynamic `ModelSpec` catalog (`LitellmCatalog`), with defaults in `config.py`.
3. **Scene**: `extraction.ocr`, `extraction.vision`, `extraction.json`, `advisor.chat`, `statement.summary` (`SceneBinding` in DB tables `llm_providers`, `llm_scene_bindings`).

## <a id="agent"></a>The model entry point (#3153, switch in progress)

`apps/backend/src/llm/extension/agent.py` is the one place that calls `infra2_sdk.runtime.create_llm_agent`. `complete_text(call_site, role, content, decoding=...)` returns the reply text; `stream_text(...)` yields it in pieces. `CallSite` names each call site; the SDK puts it on the telemetry as `infra.llm.call_site`. The SDK owns the provider client, the retry of a model error, the redaction of an error and the `gen_ai.*` telemetry.

Moved call sites: `reconciliation.semantic_score`. The other call sites still use the `litellm` path and the cassettes below until their PR of #3153.

Tests: `apps/backend/tests/conftest.py` sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`, so no test reaches a provider. A test gives a fake model with the fixture `fake_llm`, or replays a recording with `@pytest.mark.vcr` and the fixture `vcr_llm`. A recording answers only the request body that it was recorded for. Record again: `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>`. Product code imports no fake model and no recorder (`tests/tooling/test_llm_cassette_boundary.py`).

## <a id="cassettes"></a>Record/Replay Cassettes

`apps/backend/src/llm/extension/cassette.py` wraps non-streaming and streaming (`litellm_stream` via `CassetteOptions`) provider calls with `LLM_CASSETTE_MODE`:
- `replay` (CI default, no network; misses fail closed with `CassetteMiss`),
- `record` (`make llm-record` / `pytest --llm-record`),
- `off` (live execution for dev/staging `-m llm` gates).

Fingerprints hash normalized `(role, messages, decode_params, image_sha256)`, independent of exact model ID. Cassettes live under `tests/fixtures/llm_cassettes/` and are tagged `correctness` (`CassetteTag.CORRECTNESS` + validator) or `flow-only`. Never hand-author cassettes.

## <a id="cassette-graded-eval"></a>Cassette Graded Field-Accuracy Eval + Drift Ratchet

`tools/check_cassette_graded_eval.py` scores cassettes against synthetic/strictly-redacted ground truth (`tests/fixtures/llm_cassettes/ground_truth/<fingerprint>.truth.json`, Decimal-exact amounts) and enforces raise-only per-case floors in `cassette-eval-baseline.jsonl` plus `cassette-corpus-count-baseline.json` (minimum matrix across `text` and `vision`). Drift detection is bounded to the covered matrix, a single sample is only a point estimate, and live provider accuracy on unseen PDFs stays verified on Staging (`staging_gate` and `scheduled_audit`).
