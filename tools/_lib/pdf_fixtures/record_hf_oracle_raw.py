#!/usr/bin/env python
"""Record the HF oracle FAST: per-page, parallel, non-streaming raw z.ai.

Why this exists (measured): our production extractor STREAMS a single
all-pages-in-one-call request -> ~30s/page and ~290s for a 6-page/162-txn
statement. A non-streaming raw call is ~14s/page, and a statement's pages are
independent, so extracting them **in parallel** is ~14s/statement. With a global
concurrency cap this records 40 statements in minutes.

OPERATOR-ONLY, KEYED: needs a z.ai key in ``ZAI_API_KEY`` (or ``GLM_CODING_TOKEN``).
Uses the coding endpoint + ``glm-4.6v`` by default (overridable). Persists one
record per statement to ``apps/backend/tests/fixtures/hf_oracle/``: the LLM's
**raw per-page output** (verbatim) + the HF ``truth`` label — nothing code-derived
(Axiom D). Parsing/merging/validating/scoring is the CODE layer
(``tests/extraction/hf_oracle_codec.py``). This dir is its OWN dataset —
deliberately NOT the balance-gated ``llm_cassettes`` dir, since real OCR has
errors that won't satisfy the balance-chain invariant (AC23.7).

    cd <repo> && ZAI_API_KEY=$GLM_CODING_TOKEN \\
        uv run --directory apps/backend python ../../tools/_lib/pdf_fixtures/record_hf_oracle_raw.py --per-dir 5
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "tmp" / "input" / "hf_oracle"
# Its OWN dataset dir — NOT the balance-gated llm_cassettes dir. Real OCR has
# errors (won't satisfy opening+Σ≈closing), so it must not go through AC23.7's
# balance-chain gate. Each entry is self-contained: our extraction + the truth + score.
ORACLE_DIR = REPO_ROOT / "apps" / "backend" / "tests" / "fixtures" / "hf_oracle"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT))
from hf_oracle_truth import build_truth  # noqa: E402

ENDPOINT = (
    os.environ.get("ZAI_BASE", "https://api.z.ai/api/coding/paas/v4")
    + "/chat/completions"
)
MODEL = os.environ.get("HF_OCR_MODEL", "glm-4.6v")
RENDER_SCALE = 1.6
CONCURRENCY = int(os.environ.get("HF_CONCURRENCY", "10"))
PROMPT = (
    "Extract this bank-statement page as strict JSON only (no prose, no markdown "
    "fence): {opening_balance, closing_balance, transactions:[{date, description, "
    "amount, direction, balance_after}]}. amount = absolute value; direction = "
    '"IN" for credits / "OUT" for debits; balance_after = the running balance '
    "printed on that row. Omit opening_balance/closing_balance if not on this page."
)


async def _page_extract(client, key: str, png_b64: str, sem: asyncio.Semaphore) -> str:
    """Return the RAW model output text (persisted verbatim — the LLM artifact).
    Parsing/normalising is the CODE layer's job (hf_oracle_codec), kept out of here."""
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{png_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 8192,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    async with sem:
        for attempt in range(6):  # absorb the coding plan's tight rate limit
            r = await client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=120,
            )
            if r.status_code == 429:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            break
    r.raise_for_status()
    return (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")


MAX_DIM = int(os.environ.get("HF_MAX_DIM", "2200"))  # cap long side (px)


def _render_pages(pdf: Path) -> list[str]:
    """Render pages, capping the long side at MAX_DIM. Scanned PDFs embed huge
    hi-res images (e.g. 3970x5613 -> 22MB -> z.ai '1261 Prompt too long'); capping
    fixes the 400 AND cuts vision tokens (faster). Never upscales past RENDER_SCALE."""
    import fitz

    doc = fitz.open(pdf)
    out = []
    for i in range(len(doc)):
        page = doc.load_page(i)
        long_side = max(page.rect.width, page.rect.height) or 1
        scale = min(RENDER_SCALE, MAX_DIM / long_side)
        png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes(
            "png"
        )
        out.append(base64.b64encode(png).decode())
    return out


async def _record_statement(client, key, pdf: Path, sem: asyncio.Semaphore) -> dict:
    hf = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    truth = build_truth(hf, dirname=pdf.parent.name)
    pages_b64 = _render_pages(pdf)
    t = time.monotonic()
    raw_pages = await asyncio.gather(
        *[_page_extract(client, key, b, sem) for b in pages_b64]
    )
    dt = time.monotonic() - t

    out = {
        "source": f"{pdf.parent.name}/{pdf.name}",
        "model": MODEL,
        "prompt": PROMPT,
        "synthetic": True,  # HF dataset is synthetic (Apache-2.0); no real PII.
        "modality": truth["modality"],
        "pages": len(pages_b64),
        "raw_pages": list(
            raw_pages
        ),  # RAW LLM output per page — the persisted artifact
        "truth": truth["expected"],  # independent HF label (production schema)
    }
    name = f"{pdf.parent.name}__{pdf.stem}.json"
    (ORACLE_DIR / name).write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "pdf": str(pdf.relative_to(CORPUS_DIR)),
        "pages": len(pages_b64),
        "sec": round(dt, 1),
    }


async def _main(per_dir: int) -> int:
    import httpx

    key = os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_CODING_TOKEN")
    if not key:
        print("Set ZAI_API_KEY (or GLM_CODING_TOKEN) — keyed record step.")
        return 1
    # Balanced: the first `per_dir` numbered files from EACH of the 4 folders.
    pdfs: list[Path] = []
    for d in sorted(
        p for p in CORPUS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        pdfs.extend(sorted(d.glob("[0-9]*.pdf"))[:per_dir])
    if not pdfs:
        print(f"No corpus under {CORPUS_DIR}; run fetch_hf_oracle.py first.")
        return 1
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_record_statement(client, key, p, sem) for p in pdfs],
            return_exceptions=True,
        )
    ok = 0
    for r in results:
        if isinstance(r, Exception):
            print(f"  FAIL: {type(r).__name__}: {str(r)[:70]}")
        else:
            ok += 1
            print(f"  {r['pdf']}: {r['pages']} raw page(s) ({r['sec']}s)")
    print(
        f"Recorded {ok}/{len(pdfs)} raw -> {ORACLE_DIR.relative_to(REPO_ROOT)} "
        "(score via the codec test, not here)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--per-dir", type=int, default=5, help="files per folder (4 folders)"
    )
    return asyncio.run(_main(ap.parse_args(argv).per_dir))


if __name__ == "__main__":
    raise SystemExit(main())
