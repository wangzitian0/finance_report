# Cassette Graded Field-Accuracy Eval + Drift Ratchet

> SSOT owner for the **graded LLM extraction eval** over committed cassettes
> (EPIC-023 AC23.8, issue #1307). The balance-chain integrity gate
> ([`common/llm/readme.md#cassettes`](https://github.com/wangzitian0/finance_report/blob/main/common/llm/readme.md#cassettes),
> AC23.7) is the *consistency* oracle; this is the *accuracy* oracle.

## 1. Why a graded eval (what the balance gate cannot see)

The committed record/replay cassettes are gated today by the **balance-chain
invariant** `opening + Σ amounts ≈ closing` (`tools/check_llm_cassettes.py`,
AC23.7). That catches an **inconsistent** re-recording, but it is blind to
**inaccuracy**: an LLM that reads `50` as `150` — or swaps two transaction
amounts so the net is unchanged — still satisfies the chain. Such a cassette is
*plausible but wrong*.

This graded eval scores each committed statement cassette **per field** against a
known-correct **ground-truth** artifact, producing a numeric `[0, 1]` accuracy
score per case, and ratchets a per-case **score floor** that may only go **UP**.
The gate fails CI when a refreshed cassette regresses a case below its floor —
including the "balance still reconciles but a field is now wrong" case.

## 2. Ground-truth source (synthetic only)

Each scored cassette `<fingerprint>.json` has a sibling ground-truth manifest
`apps/backend/tests/fixtures/llm_cassettes/ground_truth/<fingerprint>.truth.json`:

```json
{
  "synthetic": true,
  "modality": "text",
  "institution_class": "generic",
  "edge_condition": "happy_path",
  "expected": { "opening_balance": "...", "closing_balance": "...", "transactions": [ ... ] }
}
```

- **Data hygiene (AC, enforced):** every ground-truth artifact MUST set
  `"synthetic": true`. The inputs are **synthetic / anonymised** — never real
  financial data. The test `test_AC23_8_6_ground_truth_artifacts_are_synthetic`
  enforces the flag.
- `expected` carries the known-correct field values; the matching cassette
  supplies the LLM's frozen extraction to score against it.

## 3. Scoring & normalisation

A case score is the fraction of **scored fields** that match ground truth:

| Field | Match rule |
|-------|-----------|
| `opening_balance`, `closing_balance` | Decimal equality (never float) |
| transaction `amount` | Decimal equality (`"5.00" == 5 == 5.0`) |
| transaction `date` | ISO `YYYY-MM-DD` (slash forms normalised) |
| transaction `description` | case-folded, whitespace-collapsed |

A missing expected transaction row scores its fields as wrong; an **invented**
extra row is penalised as fully wrong. Money is compared as `Decimal`
end-to-end so `0.10 × 3 == 0.30` holds exactly.

## 4. Ratchet (floor only goes up)

The per-case floor is persisted as sorted, line-oriented JSONL at
`docs/ssot/cassette-eval-baseline.jsonl` (one case per line, `merge=union` in
`.gitattributes` so PRs ratcheting different cases auto-merge). This mirrors the
established AC behavioural-score ratchet (`docs/ssot/ac-score-baseline.jsonl`,
`common/ssot/check_ac_score_baseline.py`):

- **Gate:** `tools/check_cassette_graded_eval.py` fails if any case scores below
  its floor (minus a tiny epsilon), if a baselined case lost its floor, **or if a
  committed case has no floor at all** — so adding a case (or accidentally
  deleting its baseline line) cannot silently disable the ratchet while CI stays
  green.
- **Raise only:** `--update` raises the floor to the current scores and never
  lowers it; it adopts new cases (the sanctioned way to baseline a freshly added
  case) but refuses to cement a run that has a regression or missing case.
- The baseline is a **persisted** floor — it is never regenerated from current
  scores (that would erase the floor).

## 5. Coverage matrix (and its bounds)

The eval set covers a **modality × institution-class × edge-condition** matrix:

| Case (cassette) | Modality | Institution class | Edge condition |
|-----------------|----------|-------------------|----------------|
| `d69fbafc…` | text | generic | happy_path |
| `cb5dd1f7…` | text | generic | duplicate_rows (#1254) |
| `d2bef919…` | vision | named_bank | happy_path |

Minimum case count: **3** (`MIN_CASES`). Required axes asserted by
`test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count`: both modalities
(`text`, `vision`), ≥2 institution classes, and the `happy_path` +
`duplicate_rows` edge conditions.

**Drift-detection power is BOUNDED by this breadth (no overclaiming).** The gate
only detects regressions on the modality / institution-class / edge-condition
combinations present in the matrix above. **CI green is NOT a correctness
guarantee on an UNSEEN statement** — a layout, institution, or edge condition not
represented here is invisible to this gate. Live correctness on unseen documents
remains the staging `-m llm` gate's job ([`common/llm/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/llm/readme.md)). Grow the matrix by
recording new cassettes + ground truth and adopting their floors via `--update`.

## 6. Reliability over N samples

When a case has **N≥2** recordings (multiple cassettes of the same logical
statement), its score is the **mean** over samples (`reliability_score`),
smoothing per-run nondeterminism. **A single sample is a point estimate, NOT a
reliability measure** — one recording cannot distinguish a stable extraction from
a lucky one. To measure reliability for a case, record multiple samples; until
then a single-sample case is scored as a point estimate and documented as such.

## 7. Determinism & refresh

The eval is **pure Python**: no network, no API key, no DB. It runs in the CI
**lint** job alongside `check_llm_cassettes` so it never perturbs the AC
behavioural-score aggregator. Scoring is deterministic on the committed fixtures.

Refresh is a **local** operation (never CI): re-record the cassettes against a
live provider with `make llm-record`, then raise the floors:

```bash
make llm-record                                   # re-record cassettes (needs a provider key)
python tools/check_cassette_graded_eval.py --update   # raise the per-case floors
```

Commit the refreshed cassettes and the raised baseline together.
