#!/usr/bin/env python
"""Record HF-oracle extraction cassettes + write their sibling ground truth.

OPERATOR-ONLY, KEYED LOCAL STEP — record mode does a REAL provider call (there is
no key in CI). Mirrors the vision path of
``apps/backend/tests/extraction/test_extraction_cassette_replay.py``: it runs the
PRODUCTION extractor (``ExtractionService.extract_financial_data``) over each
fetched HF statement in ``record`` mode, which freezes the response as a cassette
keyed by the request fingerprint (rendered-image bytes + prompt). For each new
cassette it then writes ``ground_truth/<fingerprint>.truth.json`` from the HF
label (via :mod:`hf_oracle_truth`), so the graded eval can score the frozen
extraction against an independent label.

Pipeline: ``fetch_hf_oracle.py`` (corpus) -> THIS (record + truth) ->
``tools/check_cassette_graded_eval.py --update`` (raise the per-case floor).

Run from the repo root with a provider key (GLM coding plan shown):

    cd apps/backend && \\
    AI_PROVIDER=zai AI_BASE_URL=https://api.z.ai/api/coding/paas/v4 \\
    AI_API_KEY=$GLM_CODING_TOKEN PRIMARY_MODEL=glm-5.2 \\
    OCR_MODEL=glm-4.6v VISION_MODEL=glm-4.6v LLM_CASSETTE_MODE=record \\
        uv run python ../../tools/_lib/pdf_fixtures/record_hf_oracle.py

The recorded cassettes + truth manifests are committed (synthetic, Apache-2.0);
the source PDFs stay under git-ignored ``tmp/input/hf_oracle/``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "tmp" / "input" / "hf_oracle"

# Resolve imports regardless of CWD: this dir (hf_oracle_truth), the backend src
# tree (src.*), and the repo root (common.*).
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hf_oracle_truth import build_truth  # noqa: E402


def _is_statement_cassette(path: Path) -> bool:
    """True only for an extraction cassette whose response parses to a statement
    dict (``transactions``). A single extract may also record non-statement
    intermediate cassettes; writing truth for those would create unscorable
    ground truth that breaks the graded-eval gate."""
    from common.ssot.check_llm_cassettes import _response_text

    try:
        text = _response_text(json.loads(path.read_text(encoding="utf-8"))).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        obj = json.loads(text)
    except (ValueError, KeyError, OSError):
        return False
    return isinstance(obj, dict) and "transactions" in obj


async def _record_pair(
    pdf: Path, dirname: str, service: object, cassette_dir: Path, truth_dir: Path
) -> list[str]:
    """Record one statement; write truth ONLY for new statement-shaped cassettes."""
    hf_label = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    truth = build_truth(hf_label, dirname=dirname)

    before = {p.name for p in cassette_dir.glob("*.json")}
    await service.extract_financial_data(  # type: ignore[attr-defined]
        file_content=pdf.read_bytes(), institution="HF-IN", file_type="pdf", filename=pdf.name
    )
    new = sorted({p.name for p in cassette_dir.glob("*.json")} - before)

    fingerprints = []
    for name in new:
        if not _is_statement_cassette(cassette_dir / name):
            continue  # skip non-statement intermediate cassettes
        fp = name[: -len(".json")]
        (truth_dir / f"{fp}.truth.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        fingerprints.append(fp)
    return fingerprints


def main(argv: list[str] | None = None) -> int:
    from src.llm.cassette import CassetteMode, current_mode
    from src.services.extraction.service import ExtractionService

    # Keyed RECORD step: require record mode explicitly (replay/off would miss or
    # silently no-op, masking operator error).
    if current_mode() is not CassetteMode.RECORD:
        print(
            "This is the keyed RECORD step — set LLM_CASSETTE_MODE=record + a "
            "provider key (see module docstring). Refusing to run in "
            f"{current_mode().value!r} mode."
        )
        return 1

    service = ExtractionService()
    if not service.api_key:
        print(
            "No provider key configured (AI_API_KEY). Record mode does a REAL call; "
            "set the provider env (see module docstring) and retry."
        )
        return 1

    from common.ssot.check_llm_cassettes import CASSETTE_DIR

    truth_dir = CASSETTE_DIR / "ground_truth"
    truth_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(p for p in CORPUS_DIR.glob("*/[0-9]*.pdf"))
    if not pdfs:
        print(f"No corpus under {CORPUS_DIR}; run fetch_hf_oracle.py first.")
        return 1

    total = 0
    for pdf in pdfs:
        fps = asyncio.run(_record_pair(pdf, pdf.parent.name, service, CASSETTE_DIR, truth_dir))
        total += len(fps)
        rel = pdf.relative_to(CORPUS_DIR)
        print(f"  {rel}: {', '.join(f[:12] + '…' for f in fps) or 'no statement cassette'}")
    print(f"Recorded {total} cassette(s) + truth. Now: python tools/check_cassette_graded_eval.py --update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
