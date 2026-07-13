"""Extraction tests routed through the streaming-cassette bridge in replay.

EPIC-023 AC-llm.6 / issue #1306. These wire the first batch of LLM-touching
extraction tests onto the cassette replay path so the parse pipeline's LLM path
is exercised in CI WITHOUT a key or network. The frozen responses are REAL GLM
(glm-5.2 / glm-4.6v) completions recorded via the GLM coding plan; in replay
they are served from committed cassettes (zero key, zero network).

Recording (operator-only, needs the provider key): `make llm-record ARGS='tests/extraction/test_extraction_cassette_replay.py'`

A missing cassette is a hard MISS failure (never a skip) — in CI it goes RED
with the actionable re-record summary; locally with a provider key it auto-records.

Boundary: these assert provider-agnostic response *handling* + the balance/dedup
invariants through the parse pipeline. Provider-specific correctness on unseen
documents remains the staging ``-m llm`` live gate's job (untouched here).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.llm import accumulate_stream, stream_ai_json

# No mode fork (#1597): the cassette layer decides per request — a committed
# cassette serves everywhere (zero key, zero network); a MISS is a hard failure
# in CI and auto-records locally when a provider key exists. Re-record existing
# cassettes with the layer refresh knob: `make llm-record`.

# --- Deterministic, anonymised inputs (synthetic; no real financial data). ---
# The fingerprint keys on (role + messages + decode params), so these MUST stay
# byte-identical to what was recorded for replay to hit.
_TEXT_MODEL = "glm-5.2"
_TEXT_MAX_TOKENS = 512
_TEXT_PROMPT = (
    "Extract this bank statement as strict JSON only (no prose, no markdown "
    "fence) with keys opening_balance, closing_balance, transactions (a list of "
    "{date, description, amount}). Amounts are negative for debits, positive for "
    "credits."
)
_TEXT_STATEMENT = (
    "Opening balance: 100.00\n"
    "2026-01-02  Coffee shop        -5.00\n"
    "2026-01-05  Salary credit      +50.00\n"
    "2026-01-09  Groceries          -15.00\n"
    "Closing balance: 130.00\n"
)
_TEXT_MESSAGES = [{"role": "user", "content": _TEXT_PROMPT + "\n\n" + _TEXT_STATEMENT}]
# Ground truth the test asserts on replay (opening + net == closing). Decimal,
# never float — money invariants must not accrue float rounding artefacts.
_TEXT_OPENING = Decimal("100.00")
_TEXT_CLOSING = Decimal("130.00")
_TEXT_TOLERANCE = Decimal("0.01")
_TEXT_TXN_COUNT = 3


def _loads_tolerant(content: str) -> dict:
    """Parse a JSON object, stripping a ```json fence if the model added one."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


async def test_AC23_6_extraction_text_happy_path_via_replay() -> None:
    """Text extraction happy-path through ``litellm_stream`` replay.

    Drives a known anonymised text statement through the JSON-extraction transport
    and asserts the LLM-read numbers satisfy the balance chain
    (opening + Σamounts == closing) and the expected transaction count — exercised
    with NO network and NO API key in replay. A frozen-wrong response (LLM misread
    a number) fails these assertions, which is the point.
    """
    stream = stream_ai_json(
        messages=_TEXT_MESSAGES,
        model=_TEXT_MODEL,
        max_tokens=_TEXT_MAX_TOKENS,
        temperature=0.0,
        thinking={"type": "disabled"},
    )
    content = await accumulate_stream(stream)
    data = _loads_tolerant(content)

    # Decimal end-to-end (str() before Decimal so a JSON float never seeds it).
    opening = Decimal(str(data["opening_balance"]))
    closing = Decimal(str(data["closing_balance"]))
    txns = data["transactions"]
    net = sum((Decimal(str(t["amount"])) for t in txns), Decimal("0"))

    assert abs(opening - _TEXT_OPENING) <= _TEXT_TOLERANCE
    assert abs(closing - _TEXT_CLOSING) <= _TEXT_TOLERANCE
    assert len(txns) == _TEXT_TXN_COUNT
    # Balance-chain invariant on the LLM's extraction (the #1254-class oracle).
    assert abs((opening + net) - closing) <= _TEXT_TOLERANCE


_VISION_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "vision" / "simple_statement.pdf"


# The #1614 LLM_VISION_REPLAY gate is gone: the drifted vision cassette was
# re-recorded against the current request fingerprint (a29eeada…), so this test
# serves frozen again — zero key, zero network, no skip.
async def test_AC23_6_extraction_vision_happy_path_via_replay() -> None:
    """Text+image (vision) extraction happy-path through the default-config vision
    path (OCR_MODEL == VISION_MODEL == glm-4.6v), in replay.

    Drives a committed FIXED-BYTES statement PDF through ``ExtractionService``: the
    app renders it to a PNG (deterministic), the vision OCR call replays the frozen
    glm-4.6v response, and the result must pass the app's own balance validation —
    which uses amount+direction (IN/OUT), exactly how glm-4.6v reads a statement.
    NO network, NO key in replay.
    """
    from src.extraction.base.validation import validate_balance
    from src.extraction.extension.service import ExtractionService

    service = ExtractionService()
    # Replay performs no live call, but extract_financial_data guards on a truthy
    # api_key — supply a dummy ONLY when none is configured (replay/CI). In record
    # mode the real key from the env is preserved so recording still works.
    service.api_key = service.api_key or "replay"
    result = await service.extract_financial_data(
        file_content=_VISION_PDF.read_bytes(),
        institution="ACME",
        file_type="pdf",
        filename="simple_statement.pdf",
    )
    assert len(result["transactions"]) == 3
    # The app's own balance oracle (amount+direction aware) must reconcile.
    assert validate_balance(result)["balance_valid"] is True


_DUP_MODEL = "glm-5.2"
_DUP_MAX_TOKENS = 512
_DUP_STATEMENT = (
    "Opening balance: 1000.00\n"
    "2026-02-01  Deposit ABC        +250.00\n"
    "2026-02-01  Deposit ABC        +250.00\n"  # genuine same-date same-amount duplicate
    "2026-02-03  Service fee         -10.00\n"
    "Closing balance: 1490.00\n"
)
_DUP_MESSAGES = [{"role": "user", "content": _TEXT_PROMPT + "\n\n" + _DUP_STATEMENT}]
_DUP_OPENING = Decimal("1000.00")
_DUP_CLOSING = Decimal("1490.00")
_DUP_DEPOSIT = Decimal("250.00")


async def test_AC23_6_extraction_1254_class_dedup_balance_via_replay() -> None:
    """#1254-class duplicate-deposit behaviour through the LLM path in replay.

    Two genuine same-date/same-amount deposits must BOTH survive extraction (the
    #1254 bug dropped one), and the balance chain must reconcile — asserted on the
    frozen LLM output with NO network and NO key.
    """
    stream = stream_ai_json(
        messages=_DUP_MESSAGES,
        model=_DUP_MODEL,
        max_tokens=_DUP_MAX_TOKENS,
        temperature=0.0,
        thinking={"type": "disabled"},
    )
    content = await accumulate_stream(stream)
    data = _loads_tolerant(content)

    opening = Decimal(str(data["opening_balance"]))
    closing = Decimal(str(data["closing_balance"]))
    txns = data["transactions"]
    amounts = [Decimal(str(t["amount"])) for t in txns]
    net = sum(amounts, Decimal("0"))

    # Both same-amount deposits survived (the #1254 oracle: count is preserved)
    # and no row was dropped or invented overall.
    assert len(txns) == 3
    assert sum(1 for a in amounts if a == _DUP_DEPOSIT) == 2
    assert abs(opening - _DUP_OPENING) <= _TEXT_TOLERANCE
    assert abs(closing - _DUP_CLOSING) <= _TEXT_TOLERANCE
    assert abs((opening + net) - closing) <= _TEXT_TOLERANCE


# --------------------------------------------------------------------------- #
# #1744 — unhappy-path cassettes. AC23.6's happy-path cassettes above prove the
# transport hand-off works when the LLM read the document correctly; these
# prove it ALSO works when the frozen response is exactly the shape that
# previously broke production (#1449, #1452) — through the REAL cassette
# transport into ExtractionService.parse_document(), not a unittest.mock.patch
# of extract_financial_data() (that lower-level coverage already exists in
# test_extraction.py / test_llm_led_blocking_gate.py and is NOT duplicated
# here; what's new is proving the cassette-delivered response reaches the same
# correct behavior end-to-end through parse_document()).
#
# Carrier PDFs are throwaway synthetic fixtures (apps/backend/tests/fixtures/
# vision/unhappy_*.pdf) — their content is irrelevant; only their bytes need to
# be distinct so each gets its own cassette fingerprint. The frozen response is
# what actually drives each test, hand-authored (no live provider call).
# --------------------------------------------------------------------------- #
_VISION_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vision"


def _stub_env_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the per-user eager provider lookup (``ai_streaming._stream_ai_base``)
    resolve successfully without a real key or network, and force a
    platform-deterministic media payload so replay does not depend on
    byte-identical PyMuPDF page rendering.

    ``parse_document()`` always threads ``user_id`` down to ``stream_ai_json``, which
    resolves a provider BEFORE the cassette layer gets a chance to serve a REPLAY hit
    (the per-user path in ``_stream_ai_base`` is eager, unlike the lazy default path
    the happy-path tests above use with no ``user_id``). In CI there is no configured
    provider (env or DB) for an ad-hoc test user, so that resolution raises "No LLM
    provider configured" before the cassette is ever consulted. A non-empty
    ``ai_api_key`` makes ``EnvConfigSource`` resolve a real (unused) provider — the
    fingerprint check that actually serves the frozen response depends only on
    role/messages/decode_params, never on which provider was resolved, so this does
    not affect what gets replayed.

    A non-"zai" ``ai_provider`` also steers ``_build_vision_media_payloads`` away
    from ``_render_pdf_pages_as_image_payloads`` (PyMuPDF rasterizes the PDF to a
    PNG — the exact pixels are not guaranteed byte-identical across host platforms,
    which produced a CI-only cassette MISS despite a passing local run) and onto the
    raw-base64-PDF-bytes ``file`` payload branch instead, which is a pure function of
    the fixture's fixed bytes and therefore portable across any host."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_api_key", "sk-test-replay-dummy", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "openai-compatible-test", raising=False)


async def test_AC_llm_14_1_missing_period_falls_back_to_transaction_dates_via_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-llm.14.1: a cassette response with no period_start/period_end but valid
    transaction dates degrades gracefully (#1449) — through the real cassette
    transport into parse_document(), not a unit call to _resolve_required_period."""
    from uuid import uuid4

    from src.extraction.extension.service import ExtractionService

    _stub_env_provider(monkeypatch)
    service = ExtractionService()
    service.api_key = service.api_key or "replay"
    pdf = _VISION_DIR / "unhappy_missing_period.pdf"
    summary, transactions = await service.parse_document(
        pdf,
        institution="ACME",
        user_id=uuid4(),
        file_type="pdf",
        file_content=pdf.read_bytes(),
        original_filename=pdf.name,
    )
    assert summary.status.value != "rejected", summary.status
    assert summary.period_start == date(2026, 3, 2)
    assert summary.period_end == date(2026, 3, 20)
    assert len(transactions) == 3


async def test_AC_llm_14_2_no_recoverable_date_anywhere_rejects_cleanly_via_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-llm.14.2: a cassette response with no period fields AND no parseable
    transaction dates must still reject (a genuinely date-less document is not
    silently accepted) — through the real cassette transport, not a unit call."""
    from uuid import uuid4

    from src.extraction.extension.service import ExtractionError, ExtractionService

    _stub_env_provider(monkeypatch)
    service = ExtractionService()
    service.api_key = service.api_key or "replay"
    pdf = _VISION_DIR / "unhappy_no_dates_at_all.pdf"
    with pytest.raises(ExtractionError, match="Date is required"):
        await service.parse_document(
            pdf,
            institution="ACME",
            user_id=uuid4(),
            file_type="pdf",
            file_content=pdf.read_bytes(),
            original_filename=pdf.name,
        )


async def test_AC_llm_14_3_unreconciled_balance_quarantines_to_rejected_via_replay(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-llm.14.3: a cassette response whose balance chain does not reconcile
    quarantines to the terminal `rejected` status (#1452 — previously stuck in
    `parsing` forever) — through the real cassette transport into
    parse_document(), not a unittest.mock.patch of extract_financial_data()."""
    from sqlalchemy import select

    from src.extraction.extension.service import ExtractionService
    from src.extraction.orm.layer2 import AtomicTransaction
    from src.extraction.orm.statement_enums import BankStatementStatus

    _stub_env_provider(monkeypatch)
    service = ExtractionService()
    service.api_key = service.api_key or "replay"
    pdf = _VISION_DIR / "unhappy_balance_unreconciled.pdf"
    summary, _transactions = await service.parse_document(
        pdf,
        institution="ACME",
        user_id=test_user.id,
        file_type="pdf",
        file_content=pdf.read_bytes(),
        original_filename=pdf.name,
        db=db,
    )
    # #1452: the terminal status must actually persist (not stuck in `parsing`).
    assert summary.status == BankStatementStatus.REJECTED
    # A quarantined extraction must never persist Layer-2 financial rows — the
    # returned tuple's transactions are the pre-persistence build, not what
    # dual_write_layer2 actually wrote; assert the real persisted count (this
    # test's user is fresh/isolated, so any row for it is from this parse).
    persisted = await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
    assert persisted.scalars().all() == []
