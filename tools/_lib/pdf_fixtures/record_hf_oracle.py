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

# Importable both as the HF label mapper (this dir) and the backend src tree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))

from hf_oracle_truth import build_truth  # noqa: E402


async def _record_pair(pdf: Path, dirname: str, cassette_dir: Path, truth_dir: Path) -> list[str]:
    """Record one statement; write truth for each new cassette. Returns fingerprints."""
    from src.services.extraction.service import ExtractionService

    hf_label = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    truth = build_truth(hf_label, dirname=dirname)

    before = {p.name for p in cassette_dir.glob("*.json")}
    service = ExtractionService()
    service.api_key = service.api_key or "replay"  # record uses the real env key
    await service.extract_financial_data(
        file_content=pdf.read_bytes(),
        institution="HF-IN",
        file_type="pdf",
        filename=pdf.name,
    )
    new = sorted({p.name for p in cassette_dir.glob("*.json")} - before)

    fingerprints = []
    for name in new:
        fp = name[: -len(".json")]
        (truth_dir / f"{fp}.truth.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        fingerprints.append(fp)
    return fingerprints


def main(argv: list[str] | None = None) -> int:
    from src.llm.cassette import CassetteMode, current_mode

    if current_mode() is CassetteMode.OFF:
        print(
            "LLM_CASSETTE_MODE is off — this is the keyed record step. "
            "Set LLM_CASSETTE_MODE=record + a provider key (see module docstring)."
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
        fps = asyncio.run(_record_pair(pdf, pdf.parent.name, CASSETTE_DIR, truth_dir))
        total += len(fps)
        rel = pdf.relative_to(CORPUS_DIR)
        print(f"  {rel}: {', '.join(f[:12] + '…' for f in fps) or 'no new cassette'}")
    print(f"Recorded {total} cassette(s) + truth. Now: python tools/check_cassette_graded_eval.py --update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
