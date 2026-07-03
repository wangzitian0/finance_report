#!/usr/bin/env python
"""Record the HF statement corpus as PII-safe, source-referenced cassette fixtures.

The committed test artifact is the **masked extraction output** plus a **source
reference** (an HF dataset URL, or a sha256 for a local/own statement) — never the
source PDF or its rendered images. So there is no document to leak (PII) and no repo
bloat, while the graded-eval (field accuracy) and balance-chain gates still run on the
committed response.

Engine: **GLM-4.6V** on the z.ai coding plan (no daily quota), thinking disabled so
the visible output isn't truncated, pages rendered as compressed JPEG so even scanned
statements fit the context (a raw scanned render is ~22MB → 1261). Records both HF
schemas (Type1/Type2, digital + scanned).

PII masking (uniform for synthetic HF and real own): identity meta -> ``**``,
descriptions -> first3+``***``+last3, flow values kept (see ``extraction_pii_mask``).
The ground-truth file is masked the same way so field scoring is masked-vs-masked.

Re-record only on change via a manifest (source bytes sha + prompt sha); orphans pruned.

Run from repo root with the coding token in direnv::

    GLM_CODING_TOKEN=… python tools/_lib/record_hf_cassettes.py

Recorder only — makes live GLM calls and writes fixtures; never imported by tests.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# fitz / PIL / httpx are imported lazily inside the live recorder functions so the pure
# data-shaping helpers (and their tests) import cleanly where those heavy deps aren't
# installed (e.g. the tooling-coverage CI env).

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(
    0, str(ROOT / "apps/backend")
)  # for src.* (the cassette/prompt modules)
sys.path.insert(0, str(ROOT))  # for the tools.* package

from src.llm.extension.cassette import fingerprint  # noqa: E402
from src.extraction.extension.prompts.statement import SYSTEM_PROMPT  # noqa: E402
from tools._lib.fixtures.extraction_pii_mask import mask_extraction, source_ref  # noqa: E402

CASSETTE_DIR = ROOT / "common/testing/fixtures/llm_cassettes"
TRUTH_DIR = CASSETTE_DIR / "ground_truth"
INPUT_ROOT = ROOT / "tmp/input/hf_oracle"
MANIFEST = ROOT / "tmp/hf_cassette_manifest.json"

HF_REPO = "Akashved/Indian-Bank-Statements"
HF_TYPES = (
    "India_Bank_Statement_Digital_Type1",
    "India_Bank_Statement_Digital_Type2",
    "India_Bank_Statement_Scanned_Type1",
    "India_Bank_Statement_Scanned_Type2",
)
PER_TYPE = 5
CODING_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
MODEL = "glm-4.6v"
MAX_TOKENS = 32768
JPEG_MAX_DIM = 1500
JPEG_QUALITY = 75
RETRY_BACKOFF_S = (10, 20, 40, 60)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _num(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(x).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def hf_url(key: str, ext: str = "pdf") -> str:
    return f"https://huggingface.co/datasets/{HF_REPO}/blob/main/train/{key}.{ext}"


def fetch_sources() -> list[tuple[str, Path, Path]]:  # pragma: no cover
    """Ensure the HF (pdf, truth-json) pairs are in the git-ignored cache; return (key, pdf, json)."""
    from huggingface_hub import hf_hub_download

    import shutil

    out: list[tuple[str, Path, Path]] = []
    for t in HF_TYPES:
        for i in range(1, PER_TYPE + 1):
            stem = f"{i:05d}"
            dst = INPUT_ROOT / t
            dst.mkdir(parents=True, exist_ok=True)
            pdf, js = dst / f"{stem}.pdf", dst / f"{stem}.json"
            for ext, local in (("pdf", pdf), ("json", js)):
                if not local.exists():
                    p = hf_hub_download(
                        HF_REPO,
                        repo_type="dataset",
                        filename=f"train/{t}/{stem}.{ext}",
                        local_dir=str(dst / "_hf"),
                    )
                    shutil.copy(p, local)
            out.append((f"{t}/{stem}", pdf, js))
    return out


def render_jpeg_pages(pdf_bytes: bytes) -> list[str]:  # pragma: no cover
    """Render every page to a dim-capped JPEG data URL — small enough that even a
    scanned statement fits the context (raw PNG render is ~22MB → 1261)."""
    import fitz  # type: ignore[import-untyped]
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    urls: list[str] = []
    try:
        for page in doc:
            scale = min(2.0, JPEG_MAX_DIM / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=JPEG_QUALITY)
            urls.append(
                "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            )
        return urls
    finally:
        doc.close()


def build_messages(image_urls: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "Extract this bank statement (all pages)."}
    ]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in image_urls]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def strip_request_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with every image data-URL replaced by a content
    hash. The committed cassette must NEVER carry raw page-image bytes (repo bloat, and
    real PII for own statements); the hash is enough to identify the request shape, and
    full replay re-renders from the referenced source anyway."""
    out: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            out.append(m)
            continue
        parts: list[Any] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = str((part.get("image_url") or {}).get("url", ""))
                digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
                parts.append({"type": "image_url", "image_bytes_sha256": digest})
            else:
                parts.append(part)
        out.append({**m, "content": parts})
    return out


def glm_extract(messages: list[dict[str, Any]], token: str) -> str:  # pragma: no cover
    """Live GLM-4.6V call (thinking disabled) with transient-error backoff; return raw text."""
    import httpx

    body = {
        "model": MODEL,
        "stream": False,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "messages": messages,
    }
    last = ""
    for delay in (0, *RETRY_BACKOFF_S):
        if delay:
            time.sleep(delay)
        r = httpx.post(
            CODING_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=600,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"] or ""
        last = f"{r.status_code} {r.text[:120]}"
        if not re.search(
            r"50[23]|429|high demand|UNAVAILABLE|overloaded|rate|1210|Invalid API parameter",
            last,
            re.I,
        ):
            raise RuntimeError(f"GLM error: {last}")
    raise RuntimeError(f"GLM failed after retries: {last}")


def _iso_date(value: Any) -> str:
    s = str(value or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s[:10]


def _row_amount(r: dict) -> Decimal:
    amt = _num(r.get("transaction_amount"))
    if amt is not None:
        return abs(amt)
    credit, debit = (
        _num(r.get("credit")) or Decimal(0),
        _num(r.get("debit")) or Decimal(0),
    )
    return credit if credit else debit


def _row_balance(r: dict) -> Decimal | None:
    return (
        _num(r.get("balance"))
        if r.get("balance") is not None
        else _num(r.get("available_balance"))
    )


def build_truth(hf_json: dict, *, modality: str) -> dict:
    """HF labels -> graded-eval truth shape, then MASKED the same way as the response
    (so field scoring is masked-vs-masked). Balance not asserted (HF balance column is
    internally inconsistent) -> ``balance_reconciles: false`` exempts AC23.7."""
    tx = hf_json.get("transactions", [])
    rows = [
        {
            "date": _iso_date(r.get("date", "")),
            "description": str(r.get("description", "")),
            "amount": str(_row_amount(r)),
        }
        for r in tx
    ]
    first_bal = _row_balance(tx[0]) if tx else None
    last_bal = _row_balance(tx[-1]) if tx else None
    expected = {
        "opening_balance": str(first_bal) if first_bal is not None else None,
        "closing_balance": str(last_bal) if last_bal is not None else None,
        "transactions": rows,
    }
    return {
        "synthetic": True,
        "modality": modality,
        "institution_class": "generic_hf",
        "edge_condition": "large_statement",
        "balance_reconciles": False,
        "note": (
            "SYNTHETIC statement (Akashved/Indian-Bank-Statements; generated, no real data). "
            "Source not committed — see the cassette's source.url. Balance NOT asserted "
            "(dataset balance column is internally inconsistent); field accuracy is graded. "
            "PII-masked uniformly (meta -> **, description -> first3***last3)."
        ),
        "expected": mask_extraction(expected),
    }


def _load_manifest() -> dict[str, Any]:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _prompt_sha() -> str:
    return _sha(SYSTEM_PROMPT.encode("utf-8"))


def main() -> int:  # pragma: no cover
    token = os.environ["GLM_CODING_TOKEN"]
    sources = fetch_sources()
    manifest = _load_manifest()
    prompt_sha = _prompt_sha()
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    recorded = skipped = 0

    for key, pdf, hf_json_path in sources:
        pdf_bytes = pdf.read_bytes()
        src_sha = _sha(pdf_bytes)
        prior = manifest.get(key)
        fp_exists = prior and (CASSETTE_DIR / f"{prior['cassette_fp']}.json").exists()
        if (
            prior
            and prior["source_sha"] == src_sha
            and prior["prompt_sha"] == prompt_sha
            and fp_exists
        ):
            print(f"SKIP   {key}")
            skipped += 1
            continue
        if prior and fp_exists:  # prompt/source changed -> prune stale
            (CASSETTE_DIR / f"{prior['cassette_fp']}.json").unlink(missing_ok=True)
            (TRUTH_DIR / f"{prior['cassette_fp']}.truth.json").unlink(missing_ok=True)

        messages = build_messages(render_jpeg_pages(pdf_bytes))
        decode_params = {"max_tokens": MAX_TOKENS, "temperature": 0.0}
        raw = glm_extract(messages, token)
        body = raw.strip()
        if body.startswith("```"):
            body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            extracted = json.loads(body)
        except json.JSONDecodeError:
            print(f"WARN   {key}: response not JSON, skipping")
            continue
        masked = mask_extraction(extracted)
        # Key the cassette on the SAME (image-stripped) request that gets stored, so the
        # committed file round-trips `fingerprint(stored request) == filename` (AC23.5.2)
        # and no raw page-image bytes are committed (repo bloat / PII).
        stored_request = {
            "role": "vision",
            "messages": strip_request_images(messages),
            "decode_params": decode_params,
        }
        fp = fingerprint(
            role="vision",
            messages=stored_request["messages"],
            decode_params=decode_params,
        )
        cassette = {
            "fingerprint": fp,
            "role": "vision",
            "tag": "flow-only",
            "source": source_ref(hf_url=hf_url(key)),
            "request": stored_request,
            "response": {"stream_text": json.dumps(masked, ensure_ascii=False)},
        }
        (CASSETTE_DIR / f"{fp}.json").write_text(
            json.dumps(cassette, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        modality = "vision" if "Scanned" in key else "text"
        truth = build_truth(
            json.loads(hf_json_path.read_text(encoding="utf-8")), modality=modality
        )
        (TRUTH_DIR / f"{fp}.truth.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest[key] = {
            "source_sha": src_sha,
            "prompt_sha": prompt_sha,
            "cassette_fp": fp,
        }
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        recorded += 1
        print(
            f"REC    {key} -> {fp[:14]} ({len(masked.get('transactions', []))} txns, masked)"
        )

    print(f"\nDONE: recorded {recorded}, skipped {skipped}, of {len(sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
