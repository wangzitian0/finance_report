# `llm` — Provider Abstraction SSOT

> **SSOT Key**: `llm_provider_abstraction` | Implementation: `apps/backend/src/llm/`.

Owns the `LLMClient` protocol (`LitellmClient`, `DecodeParams`, `estimate_tokens`), Fernet/MultiFernet at-rest encryption (`LLM_ENCRYPTION_KEYS`, `SecretCipher.rotate()`), and deterministic CI record/replay cassettes.

## <a id="axes"></a>The Three Axes

1. **Protocol family**: `openai-compatible` (OpenAI, Z.AI/GLM `glm-5.3-flash`, DeepSeek, vLLM), `anthropic-compatible`, `openrouter-compatible`, `google-gemini`.
2. **Model**: Dynamic `ModelSpec` catalog (`LitellmCatalog`), with defaults in `config.py`.
3. **Scene**: `extraction.ocr`, `extraction.vision`, `extraction.json`, `advisor.chat`, `statement.summary` (`SceneBinding` in DB tables `llm_providers`, `llm_scene_bindings`).

## <a id="agent"></a>The model entry point (#3153, switch in progress)

`apps/backend/src/llm/extension/agent.py` is the one place that calls `infra2_sdk.runtime.create_llm_agent`. `complete_text(call_site, role, content, decoding=...)` returns the reply text; `async with stream_text(...) as pieces:` gives it in pieces and closes the stream at the end of the block. Both stream the reply, so `DecodingSpec.timeout` is the longest wait for the next chunk. `CallSite` names each call site; the SDK puts it on the telemetry as `infra.llm.call_site`. The SDK owns the provider client, the retry of a model error before the first byte of the answer (`max_attempts`; a stream that fails after output has started is not retried), the redaction of an error and the `gen_ai.*` telemetry.

Facts measured against Z.AI that the entry point fixes: the SDK sends `DecodingSpec.max_tokens` as `max_completion_tokens`, which Z.AI ignores (a cap of 20 gave 504 tokens), so the entry point sends it as `max_tokens` in `extra_body` for the provider `zai` (another provider keeps the SDK field); a caller sets neither `thinking` nor `max_tokens` in `extra_body`; a reply without text is an error and not a second request (`retries=0`). The provider comes from `settings.to_llm_settings()` only: the DB layer of providers (`llm_providers`) is not read by a moved call site.

**Errors.** Each failure of a model call leaves the entry point as one `ModelCallFailed` (`src/llm/base/errors.py`, a `LLMError`, so it maps to HTTP) with a `kind`: `rate_limit` (429), `timeout` (504), `unavailable` (503), `rejected` (502), `usage_limit` (429), `not_configured` (503), `bad_reply` (502), `unclassified` (502). It is counted once in `finance.llm.call.failed{call_site, kind}`. An `unclassified` failure is logged as an ERROR (an actionable fault) and the others as a WARNING. The SDK keeps the class of a provider error and turns every other error into a bare `RuntimeError` without the cause, so a caller cannot tell a provider fault from a bug by its class: the entry point reads the class where the SDK kept it, the label of the redacted summary for an unusable reply, and marks the rest `unclassified`. A call site catches `ModelCallFailed` and nothing broader, and a failure is never turned into a value that looks like an answer: `ai_semantic_score` raises, and the matching keeps the algorithmic score and sets `ai_semantic_unavailable` in the breakdown. The entry point does not wrap its own argument errors, `CancelledError`, or the refusals of a test run. The test guard against external I/O inside an open transaction raises `UnexpectedExternalIO`, a `BaseException`, and records the violation; its fixture fails the test at teardown unless the test took the record. Ruff selects `BLE`: a blind `except Exception` must re-raise or carry `# noqa: BLE001 - <reason>`; `per-file-ignores` lists the files that still hold one (the list only shrinks, `tests/tooling/test_blind_except_work_list.py`).

Moved call sites: `reconciliation.semantic_score`. The other call sites still use the `litellm` path and the cassettes below until their PR of #3153.

Tests: `apps/backend/tests/conftest.py` sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`, so no test reaches a provider, and its guard refuses a model call while an application transaction is open (it covers the entry point, because the SDK sends through `httpx2`). A test gives a fake model with `install_fake_model` (fixture `fake_llm`, `tests/_support/fake_llm.py`; a reply function cannot fail the test with `assert`: check what was sent), or replays a recording with `@pytest.mark.vcr` and the fixture `vcr_llm` (it fails without the marker). A recording answers only the request body that it was recorded for. Record again: `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>`. Product code imports no fake model and no recorder, and only the entry point calls `create_llm_agent` (`tests/tooling/test_llm_cassette_boundary.py`). `vcr_llm` pins the default provider and models, and fails under `--disable-recording`. A fake model is more lenient than the wire: an empty reply returns the empty text, and an HTTP error class is not retried.

## <a id="cassettes"></a>Record/Replay Cassettes

`apps/backend/src/llm/extension/cassette.py` wraps non-streaming and streaming (`litellm_stream` via `CassetteOptions`) provider calls with `LLM_CASSETTE_MODE`:
- `replay` (CI default, no network; misses fail closed with `CassetteMiss`),
- `record` (`make llm-record` / `pytest --llm-record`),
- `off` (live execution for dev/staging `-m llm` gates).

Fingerprints hash normalized `(role, messages, decode_params, image_sha256)`, independent of exact model ID. Cassettes live under `tests/fixtures/llm_cassettes/` and are tagged `correctness` (`CassetteTag.CORRECTNESS` + validator) or `flow-only`. Never hand-author cassettes.

## <a id="cassette-graded-eval"></a>Cassette Graded Field-Accuracy Eval + Drift Ratchet

`tools/check_cassette_graded_eval.py` scores cassettes against synthetic/strictly-redacted ground truth (`tests/fixtures/llm_cassettes/ground_truth/<fingerprint>.truth.json`, Decimal-exact amounts) and enforces raise-only per-case floors in `cassette-eval-baseline.jsonl` plus `cassette-corpus-count-baseline.json` (minimum matrix across `text` and `vision`). Drift detection is bounded to the covered matrix, a single sample is only a point estimate, and live provider accuracy on unseen PDFs stays verified on Staging (`staging_gate` and `scheduled_audit`).
