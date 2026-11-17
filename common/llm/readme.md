# `llm` — Provider Abstraction SSOT

> **SSOT Key**: `llm_provider_abstraction` | Implementation: `apps/backend/src/llm/`.

Owns the `LLMClient` protocol (`LitellmClient`, `DecodeParams`, `estimate_tokens`), Fernet/MultiFernet at-rest encryption (`LLM_ENCRYPTION_KEYS`, `SecretCipher.rotate()`), and deterministic CI record/replay cassettes.

## <a id="axes"></a>The Three Axes

1. **Protocol family**: `openai-compatible` (OpenAI, Z.AI/GLM `glm-5.3-flash`, DeepSeek, vLLM), `anthropic-compatible`, `openrouter-compatible`, `google-gemini`.
2. **Model**: Dynamic `ModelSpec` catalog (`LitellmCatalog`), with defaults in `config.py`.
3. **Scene**: `extraction.ocr`, `extraction.vision`, `extraction.json`, `advisor.chat`, `statement.summary` (`SceneBinding` in DB tables `llm_providers`, `llm_scene_bindings`).

## <a id="cassettes"></a>Record/Replay Cassettes

`apps/backend/src/llm/extension/cassette.py` wraps non-streaming and streaming (`litellm_stream` via `CassetteOptions`) provider calls with `LLM_CASSETTE_MODE`:
- `replay` (CI default, no network; misses fail closed with `CassetteMiss`),
- `record` (`make llm-record` / `pytest --llm-record`),
- `off` (live execution for dev/staging `-m llm` gates).

Fingerprints hash normalized `(role, messages, decode_params, image_sha256)`, independent of exact model ID. Cassettes live under `common/testing/fixtures/llm_cassettes/` and are tagged `correctness` (`CassetteTag.CORRECTNESS` + validator) or `flow-only`. Never hand-author cassettes.

## <a id="cassette-graded-eval"></a>Cassette Graded Field-Accuracy Eval + Drift Ratchet

`tools/check_cassette_graded_eval.py` scores cassettes against synthetic/strictly-redacted ground truth (`common/testing/fixtures/llm_cassettes/ground_truth/<fingerprint>.truth.json`, Decimal-exact amounts) and enforces raise-only per-case floors in `cassette-eval-baseline.jsonl` plus `cassette-corpus-count-baseline.json` (minimum matrix across `text` and `vision`). Drift detection is bounded to the covered matrix, a single sample is only a point estimate, and live provider accuracy on unseen PDFs stays verified on Staging (`staging_gate` and `scheduled_audit`).
