---
name: extraction
description: Document parsing pipeline for financial statements (PDFs, images, CSVs). Use when working with statement uploads, parsing, confidence scoring, or supported institutions.
---

# Document Extraction

This skill is a **pointer, not a mirror** (#1658): the hand-written snapshot it
used to carry drifted from the owning contract, and models read the owner
directly.

**Read the owner**: [common/extraction/readme.md](../../../../common/extraction/readme.md)

Also honor the red lines in `docs/agents/red-lines.md` (Decimal for money,
balanced entries, explicit `sa.Enum` names) and the work order in
`docs/agents/orchestration.md` (AC-anchored tests before code).
