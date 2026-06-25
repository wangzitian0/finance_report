#!/usr/bin/env python
"""Fetch a small labelled bank-statement corpus from Hugging Face as an
extraction **accuracy oracle** (PDF/image -> structured table).

Unlike our generated fixtures (whose "truth" is the render source — circular for
accuracy), this dataset ships a document + an *independent* field label, and —
crucially — **scanned** variants. Recovering the label from a degraded scan is a
genuine accuracy test of the first hop (document -> structured table), not just
"read back a clean render".

The corpus lands under ``tmp/input/hf_oracle/`` (git-ignored). It is the INPUT to
the record step (``record_hf_oracle.py``), which runs our extractor in record
mode to produce a cassette and writes the sibling ground-truth manifest. Nothing
here calls an LLM or needs a key.

Dataset: https://huggingface.co/datasets/Akashved/Indian-Bank-Statements
(Apache-2.0, tagged ``synthetic`` — synthetic Indian business current-account
statements; no real PII). Digital + Scanned, two layouts each.

Usage:
    # default: scanned-weighted ~10 pairs (the real failure mode)
    python tools/_lib/pdf_fixtures/fetch_hf_oracle.py

    # the full 25-per-dir / 100-pair corpus
    python tools/_lib/pdf_fixtures/fetch_hf_oracle.py --per-dir 25

Requires: huggingface_hub
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ID = "Akashved/Indian-Bank-Statements"
REPO_TYPE = "dataset"

# The four corpus directories. Scanned is weighted higher in the default mix:
# it exercises the messy real-world failure mode (OCR of a degraded image),
# where the field label is a genuine accuracy target — the digital variants are
# clean renders, so their accuracy signal is weak (see cassette-graded-eval.md).
DIRS = (
    "India_Bank_Statement_Scanned_Type1",
    "India_Bank_Statement_Scanned_Type2",
    "India_Bank_Statement_Digital_Type1",
    "India_Bank_Statement_Digital_Type2",
)
DEFAULT_MIX = {  # scanned-weighted ~10-pair smoke corpus
    "India_Bank_Statement_Scanned_Type1": 3,
    "India_Bank_Statement_Scanned_Type2": 3,
    "India_Bank_Statement_Digital_Type1": 2,
    "India_Bank_Statement_Digital_Type2": 2,
}

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tmp" / "input" / "hf_oracle"


def _pair_ids(dirname: str, count: int) -> list[str]:
    """The first ``count`` zero-padded pair ids (``00001`` ...) in a directory."""
    return [f"{i:05d}" for i in range(1, count + 1)]


def fetch(per_dir: int | None, out_dir: Path = OUT_DIR) -> list[Path]:
    """Download ``<id>.pdf`` + ``<id>.json`` pairs into ``out_dir/<dir>/``.

    Returns the list of downloaded file paths. ``per_dir=None`` uses the
    scanned-weighted default mix; an int fetches that many from every directory.
    """
    from huggingface_hub import hf_hub_download

    mix = {d: per_dir for d in DIRS} if per_dir is not None else DEFAULT_MIX
    downloaded: list[Path] = []
    for dirname, count in mix.items():
        dest = out_dir / dirname
        dest.mkdir(parents=True, exist_ok=True)
        for pid in _pair_ids(dirname, count):
            for ext in ("pdf", "json"):
                rel = f"train/{dirname}/{pid}.{ext}"
                local = hf_hub_download(
                    repo_id=REPO_ID,
                    repo_type=REPO_TYPE,
                    filename=rel,
                    local_dir=str(out_dir / "_hf"),
                )
                target = dest / f"{pid}.{ext}"
                target.write_bytes(Path(local).read_bytes())
                downloaded.append(target)
            print(f"  {dirname}/{pid}  (pdf+json)")
    return downloaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--per-dir",
        type=int,
        default=None,
        help="pairs to fetch from EACH of the 4 dirs (default: scanned-weighted ~10 total)",
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    print(f"Fetching {REPO_ID} -> {args.out_dir}")
    paths = fetch(args.per_dir, args.out_dir)
    pairs = len(paths) // 2
    print(f"Done: {pairs} pair(s) across {len(DIRS)} dirs under {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
