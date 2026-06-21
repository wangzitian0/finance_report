# AC Authority Tiers

> **SSOT Key**: `authority_tiers`

This document owns the **authority-tier** vocabulary: a single attribute on every
acceptance criterion (AC) that records **who holds final decision authority over
the behavior the AC describes** — deterministic code, a human, or an LLM. The
tier is a property of the AC's *behavior*, not of any file or module: it travels
with the intent, so the same source file can host PC and LP behaviors and each AC
still carries its own tier.

The payoff is direct: **an AC's tier dictates what KIND of proof is valid for
it.** Tying the testing strategy to authority stops us from demanding a
bit-exact golden assertion for an LLM-owned mapping (impossible) or accepting a
smoke test for a money calculation (unsafe).

This SSOT owns the *terms*. EPIC docs declare a tier per AC (the `{tier:XX}`
marker at the AC's definition site); the registry generator lifts it into the AC
value; the ratchet gate keeps new/changed ACs from skipping it. See
[EPIC-026](../project/EPIC-026.ac-authority-tiers.md) for the horizontal goal and
[tdd.md](./tdd.md) for the surrounding EPIC -> AC -> Test workflow.

## The five tiers

| Code | Name (中文) | Authority | Reproducible? | Typical behaviors |
|------|-------------|-----------|---------------|-------------------|
| **PC** | 纯代码 pure-code | Code | Bit-level, fully reproducible, no LLM | money/accounting, dedup, validation, persistence, security, reporting-calc, types |
| **CP** | 代码为主·LLM辅助 code-primary | **Code emits the output**; the LLM may only adjust *configuration* — thresholds, which profile/strategy to run, mapping hints | Reproducible once the config is pinned (the LLM only turned knobs) | model/strategy selection feeding a deterministic parser; LLM-tuned reconciliation thresholds with deterministic scoring |
| **HU** | 人来判定 human-decides | A human adjudicates; system presents evidence + options | Decision NOT reproducible; the EVIDENCE CHAIN is | review queue, low-confidence corrections |
| **LP** | LLM为主·代码守门 LLM-primary | **The LLM emits the output/content**; code does only format constraints + sanity / invariant checks — it can reject or flag, never produce | Not reproducible but DETECTABLE | extraction, OCR, classification, brokerage CSV→canonical mapping |
| **PL** | 纯LLM pure-LLM | LLM output is the deliverable; low blast radius; no hard oracle | Not required | advisor narrative, chat answer/suggestion text |

The five tiers form one axis — **how much of the output the LLM controls, from 0
(PC) to full (PL)** — with **HU as the orthogonal escape hatch** for when neither
code nor LLM should hold authority. `CP` and `LP` are mirror images around a
single question:

> **CP vs LP — the deciding test:** is the artifact that actually gets used
> *computed by code* or *emitted by the LLM*? Code computes it and the LLM only
> turned configuration knobs → **CP**. The LLM emits it and code only
> validates / constrains it → **LP**. The line is **who emits**, not how much LLM
> is involved.

## How a tier is assigned

A tier is **bounded by the blast radius of an *undetected* error**, not by how
much LLM happens to be in the loop. Walk this order and take the first match:

1. The outcome is a human judgment with no automatable oracle → **HU**.
2. A wrong automated output could **silently become financial truth** with no
   deterministic oracle to catch it → it MUST be **PC / CP** (never LP/PL — the
   LLM is not allowed to own an unverifiable money-affecting result).
3. It maps messy input where a **deterministic invariant can catch errors and
   recover** → **LP**.
4. Code makes the final call; the LLM only tunes config / assists → **CP**.
5. Pure narrative — touches no number and persists nothing → **PL**.

Governance / scoping / architecture statements (no runtime decision authority)
default to **PC**: they are deterministic assertions, not adjudicated behavior.

## tier -> valid proof type

This matrix is the operative contract: it says which proof shape is *valid*
evidence for an AC at each tier.

| Tier | Valid proof | NOT valid |
|------|-------------|-----------|
| **PC** | Deterministic exact-assertion / property test; bit-level reproducible | — |
| **CP** | Test asserts the **code's final decision** is correct; the LLM suggestion may vary and is **not** asserted | Asserting the LLM suggestion text |
| **HU** | Test asserts the **evidence chain** is present (evidence + options surfaced) | Asserting the human's outcome |
| **LP** | Invariant/property test + graded eval + provenance | Exact "golden" assertions on the LLM output |
| **PL** | Quality/smoke eval + guardrail assertions (must not touch numbers) | Reproducibility / exact-match requirements |

## Cross-tier MUST rules

These are hard rules an AC's tier must respect; they are the safety boundary
between the deterministic core and the LLM surface.

1. **No LLM-sourced financial truth without a deterministic oracle.** LP/PL
   output MUST cross a PC oracle (validation/guard) before it is persisted as
   financial truth. An LLM never writes a ledger number unchecked.
2. **PC stays pure.** A PC AC MUST NOT depend on an LLM client; its outcome is
   produced and proven by deterministic code alone.
3. **PL owns no money.** A PL AC MUST NOT source a number or persist financial
   facts; its deliverable is narrative/UX text with low blast radius.
4. **One AC = one tier.** An AC that spans tiers is too coarse and MUST be split.
   If a behavior both extracts (LP) and validates-then-persists (PC), those are
   two ACs.

## How a tier is declared

Declare the tier at the AC's **definition site** in the EPIC doc, inline in the
requirement cell, with a `{tier:XX}` marker:

```text
| AC3.1.1 | Parse DBS PDF {tier:LP} | `test_...` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.2.1 | Balance Validation (Pass) {tier:PC} | `test_balance_valid` | ... | P0 |
```

`tools/generate_ac_registry.py` strips the marker from the description and lifts
`tier: LP` (etc.) into the AC's registry value, so the tier is a first-class
attribute of the generated AC entry. `XX` is one of `PC | CP | HU | LP | PL`.

## Ratchet gate (non-breaking adoption)

~1830 ACs predate this attribute, so coverage is adopted via a **shrink-only
debt ratchet**, mirroring the protection-floor / AC-score baselines:

- The untagged debt lives in [`ac-tier-baseline.json`](./ac-tier-baseline.json).
- `tools/check_ac_tier_baseline.py` fails only when an AC that is **new or
  modified relative to the baseline** lacks a tier. Already-untagged ACs in the
  baseline are tolerated.
- The baseline may only **shrink** (`--update` drops newly-tagged ACs and refuses
  to launder fresh debt), so the untagged count is monotonically non-increasing.

## Follow-ups (out of scope here)

- Full backfill of the remaining untagged ACs (ratcheted over time).
- A derived **module-level tier view** (aggregating AC tiers per module).
- CI enforcement of **tier -> proof-type** (e.g. rejecting an exact-golden proof
  for an LP AC, or a number-touching assertion for a PL AC).

## Related

- [tdd.md](./tdd.md) — EPIC -> AC -> Test workflow that this attribute extends.
- [EPIC-026](../project/EPIC-026.ac-authority-tiers.md) — the EPIC that introduces tiers.
- [ai.md](./ai.md), [extraction.md](./extraction.md) — domains where LP/PL/HU/CP behaviors concentrate.
