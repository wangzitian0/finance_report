# EPIC-018: AI-Driven Data Pipeline

> **Status**: 🟡 In Progress  
> **Vision Anchor**: `decision-2-event-middle-layer`  
> **Phase**: 4 (AI Enhancement)  
> **Duration**: 4-7 weeks  
> **Priority**: P1 (High Priority - Parallel with EPIC-016)  
> **Dependencies**: EPIC-003 (Statement Parsing), EPIC-004 (Reconciliation Engine), EPIC-006 (AI Advisor), EPIC-013 (Statement Parsing V2)

---

## 🎯 Objective

Maximize AI utilization across the entire data pipeline from statement upload to financial reports. Currently, AI is only used in 2 of 7 pipeline stages (extraction and chat advisor). This EPIC extends AI into classification, reconciliation, journal entry creation, and feedback learning — transforming the pipeline from "AI extracts, human does everything else" to "AI handles what it can confidently, human reviews what it can't."

**Core Principle** (from vision.md): AI is a parsing and explanation layer, not a source of record. Confidence thresholds determine auto-accept vs. human review.

## Macro Proof Ownership

- `personal-financial-report-package`
- `source-ledger-report-traceability`

## Personal Report Package Traceability Inputs

The personal financial-report package tracked by
[#563](https://github.com/wangzitian0/finance_report/issues/563) and
[#567](https://github.com/wangzitian0/finance_report/issues/567) depends on this
EPIC for source confidence, extraction provenance, review status, and
source-to-ledger-to-report traceability notes. AI remains a parsing and
explanation layer; deterministic ledger and reporting logic remain the source
of record. The package traceability appendix is delivered by
[#572](https://github.com/wangzitian0/finance_report/issues/572) through
`GET /api/reports/package/traceability`; the representative E2E fixture that
must include confidence/review provenance is tracked by
[#573](https://github.com/wangzitian0/finance_report/issues/573).

**Current Pipeline (Before)**:
```
Upload → [AI Vision] → BankStatement → [Rules Only] → Classification
  → [Hardcoded Uncategorized] → JournalEntry → [Bypass Layer 3] → Reports
  → [Read-Only AI] → Chat Insights
```

**Target Pipeline (After)**:
```
Upload → [AI Vision + Category] → BankStatement → [AI + Rules Hybrid] → Classification
  → [AI-Suggested Accounts] → JournalEntry → [Layer 3 Aware] → Reports
  → [Learning AI] → Chat Insights + Feedback Loop
```

**Success Criteria**:
- AI suggests transaction categories during extraction (≥70% accuracy)
- Classification uses AI when rules fail (ML_MODEL rule type implemented)
- Journal entries use classified categories instead of "Uncategorized"
- User corrections feed back into AI prompts (few-shot learning)
- Reports read Layer 3 classification results

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Pipeline Design | AI adds fields to extraction prompt, not new services. Classification becomes AI+rules hybrid. Feedback loop via `CorrectionLog` table. |
| 📊 **Accountant** | Data Integrity | AI suggestions are NEVER auto-posted. Must pass through review queue. Confidence thresholds: ≥85 auto-accept, 60-84 review, <60 flag. See: `docs/ssot/reconciliation.md#thresholds` |
| 💻 **Developer** | Implementation | Extend existing `extraction.py` prompt, implement `RuleType.ML_MODEL` in `classification.py`, modify `create_entry_from_txn` in `review_queue.py`. |
| 🧪 **Tester** | Validation | Test: AI category accuracy, fallback to Uncategorized when AI fails, feedback loop persistence, Layer 3→4 data flow. |
| 📋 **PM** | User Experience | Reduces manual categorization work by 70%+. User sees AI suggestions and corrects only mistakes. Corrections make future suggestions better. |
| 🤖 **AI/ML** | Model Strategy | No custom model training needed. Uses existing OpenRouter vision model with prompt engineering + few-shot examples from user corrections. |

---

## 🔗 Relationship to Other EPICs

| EPIC | Relationship |
|------|-------------|
| EPIC-003 (Statement Parsing) | Extends extraction prompt with category fields |
| EPIC-004 (Reconciliation) | Adds AI semantic scoring for 60-84 confidence matches |
| EPIC-006 (AI Advisor) | Shares OpenRouter infrastructure; advisor gains write-suggest capability |
| EPIC-013 (Statement Parsing V2) | Builds on V2's confidence scoring framework |
| EPIC-016 (Two-Stage Review) | **Complementary** — AI automates what it can, EPIC-016 handles human review for what AI can't confidently classify |
| EPIC-017 (Portfolio) | Independent — no direct dependency |
| EPIC-020 (Framework-aware reporting) | AI may suggest measurement/disclosure evidence, but EPIC-020 owns deterministic policy and trusted report boundaries |

---

## ✅ Task Checklist

### Phase 1: AI-Powered Classification — 1-2 weeks (Highest ROI)

#### 1.1 Extraction Prompt Enhancement
- [x] Add `suggested_category` and `category_confidence` fields to extraction prompt
  - File: `apps/backend/src/prompts/statement.py`
  - Categories: Food & Dining, Transport, Shopping, Utilities, Salary, Transfer, Investment, Insurance, Rent, Healthcare, Entertainment, Education, Subscriptions, Other
  - Confidence: 0.0-1.0 float returned by AI
- [x] Add `suggested_category` VARCHAR(100) and `category_confidence` DECIMAL(3,2) columns to `BankStatementTransaction`
  - File: `apps/backend/src/models/statement.py`
  - Migration: Alembic migration with nullable columns (backward compatible)
- [x] Update extraction service to parse and persist AI-returned category fields
  - File: `apps/backend/src/services/extraction.py`
  - Graceful fallback: if AI omits category, set `suggested_category=NULL`, `category_confidence=0.0`

#### 1.2 Classification Service: Implement ML_MODEL Rule Type
- [x] Implement `RuleType.ML_MODEL` match logic in `ClassificationService.evaluate_rule()`
  - File: `apps/backend/src/services/classification.py`
  - Logic: Read `suggested_category` from `BankStatementTransaction` → apply confidence threshold
  - Threshold: `category_confidence ≥ 0.7` → accept AI suggestion
  - Currently 91 lines, `ML_MODEL` case returns `False` → make it functional
- [x] Add `classify_with_ai()` method that queries extraction results before falling back to rules
  - Priority: KEYWORD_MATCH → REGEX_MATCH → ML_MODEL (AI suggestion) → Uncategorized
  - This preserves existing user-defined rules as highest priority

#### 1.3 Journal Entry: Read Classification Before Uncategorized Fallback
- [x] Modify `create_entry_from_txn()` to check classification results before defaulting to Uncategorized
  - File: `apps/backend/src/services/review_queue.py` (lines 264-359)
  - Current: `get_or_create_account(db, name="Income - Uncategorized")` / `"Expense - Uncategorized"`
  - Target: Check `TransactionClassification` for the transaction → use classified account if exists → fallback to Uncategorized
  - Account naming: `"Income - {category}"` or `"Expense - {category}"` (e.g., `"Expense - Food & Dining"`)
- [x] Ensure `get_or_create_account()` creates accounts on-demand for new AI-suggested categories
  - Auto-created accounts must be: user-scoped, correct type (Income/Expense), correct currency

#### 1.4 Tests for Phase 1
- [x] Test: AI extraction includes `suggested_category` and `category_confidence` in response
- [x] Test: Missing AI category fields gracefully default to NULL/0.0
- [x] Test: `ML_MODEL` rule type returns True when confidence ≥ 0.7
- [x] Test: `ML_MODEL` rule type returns False when confidence < 0.7
- [x] Test: Classification priority: KEYWORD > REGEX > ML_MODEL > Uncategorized
- [x] Test: `create_entry_from_txn` uses classified category when available
- [x] Test: `create_entry_from_txn` falls back to Uncategorized when no classification exists
- [x] Test: Auto-created category accounts are correct type and user-scoped

---

### Phase 2: Feedback Learning Loop — 1 week

#### 2.1 Correction Log Model
- [x] Create `CorrectionLog` model
  - File: `apps/backend/src/models/correction.py` (new)
  - Fields: `id`, `user_id`, `transaction_id`, `original_category`, `corrected_category`, `original_account_id`, `corrected_account_id`, `created_at`
  - Links to: `BankStatementTransaction`, `Account`, `User`
  - Purpose: Track every user correction for few-shot learning
- [x] Alembic migration for `correction_log` table

#### 2.2 Correction Recording API
- [x] `POST /api/corrections` — Record a user correction
  - Input: `transaction_id`, `corrected_category`, `corrected_account_id`
  - Auto-fills `original_category` from transaction's current classification
  - Returns: correction record
- [x] `GET /api/corrections/stats` — Get correction statistics
  - Return: top N corrected categories, accuracy rate per category, total corrections
  - Use for monitoring AI quality over time

#### 2.3 Few-Shot Prompt Injection
- [x] Query `CorrectionLog` for user's recent corrections (last 50)
  - Group by `original_category → corrected_category` pattern
  - Inject as few-shot examples into extraction prompt
  - Format: "Previously, transactions like '{description}' were categorized as '{corrected_category}'"
- [x] Update `apps/backend/src/prompts/statement.py` to accept correction examples
  - Add `correction_examples: list[dict]` parameter to prompt builder
  - Inject up to 10 most relevant corrections as few-shot context
- [x] Add cache for correction examples (per user, 1-hour TTL)
  - Avoid querying correction log on every extraction call

#### 2.4 Tests for Phase 2
- [x] Test: Correction log records original and corrected categories
- [x] Test: Correction stats aggregate correctly
- [x] Test: Few-shot examples injected into extraction prompt
- [x] Test: Prompt with corrections produces different output than without (mock test)
- [x] Test: Correction cache invalidates after TTL
- [x] Test: Empty correction log produces standard prompt (no few-shot)

---

### Phase 3: AI-Assisted Reconciliation — 1-2 weeks

#### 3.1 AI Semantic Scoring
- [x] Add `ai_semantic_score()` method to reconciliation service
  - File: `apps/backend/src/services/reconciliation.py`
  - Trigger: Only for candidates scoring 60-84 (review queue range)
  - Input: Transaction description pair (bank statement + journal entry memo)
  - Output: Semantic similarity score (0-100) from AI
  - Cost control: Only called for review-queue candidates, not all matches
- [x] Create `apps/backend/src/prompts/reconciliation.py` (new)
  - Prompt: "Given these two transaction descriptions, rate their semantic similarity (0-100)"
  - Include context: date proximity, amount match, account info
  - Response format: JSON with `similarity_score` and `reasoning`

#### 3.2 Hybrid Scoring Integration
- [x] Modify `calculate_match_score()` to incorporate AI semantic score
  - Current: Pure algorithmic (date, amount, description fuzzy match)
  - New: `final_score = 0.7 * algorithmic_score + 0.3 * ai_semantic_score`
  - Only applies when algorithmic score is in 60-84 range
  - Scores outside that range remain unchanged (≥85 auto-accept, <60 unmatched)
- [x] Add feature flag: `enable_ai_reconciliation` in `config.py`
  - Default: `False` (opt-in to avoid unexpected API costs)
  - When disabled: existing pure-algorithmic behavior unchanged

#### 3.3 Tests for Phase 3
- [x] Test: `ai_semantic_score()` returns score for matching descriptions
- [x] Test: `ai_semantic_score()` returns low score for unrelated descriptions
- [x] Test: Hybrid scoring only triggers for 60-84 range candidates
- [x] Test: Feature flag disables AI scoring when False
- [x] Test: Algorithmic scores ≥85 and <60 bypass AI scoring entirely
- [x] Test: Final score correctly weights algorithmic (0.7) and AI (0.3)

---

### Phase 4: Pipeline Integration & Report Fix — 1-2 weeks

#### 4.1 Reports Read Layer 3 Classification
- [x] Modify `reporting.py` to read `TransactionClassification` (Layer 3) instead of raw `JournalLine`
  - File: `apps/backend/src/services/reporting.py`
  - Current: Reports read `JournalEntry` → `JournalLine` directly, ignoring Layer 3
  - Target: Reports query `TransactionClassification` for category breakdowns
  - Fallback: If transaction has no classification, use account name as category (backward compatible)
- [x] Add category breakdown to Income Statement
  - Group expenses/income by classified category
  - Show: Category, Amount, % of Total
  - Use `TransactionClassification.assigned_category` field

#### 4.2 ReportSnapshot (Layer 4) Utilization
- [x] Implement `ReportSnapshot` generation
  - File: `apps/backend/src/models/layer4.py` (model exists but unused)
  - Generate snapshots after report computation
  - Store: report type, date range, computed data (JSONB), generated_at
  - Enable historical comparison: "This month vs last month" reports
- [x] Add `GET /api/reports/{type}/snapshots` endpoint
  - List available snapshots for a report type
  - Enable time-series trend analysis

#### 4.3 CSV Parsing via AI (Remove Hardcoding)
- [x] Add AI-powered CSV parsing as fallback for unknown institutions
  - Current: CSV parsing is hardcoded per institution (DBS, Wise, etc.)
  - New: When institution is unknown, send CSV header + sample rows to AI
  - AI returns: column mapping (date, description, amount, balance)
  - Preserve existing hardcoded parsers for known institutions (they're faster and free)
- [x] Create `apps/backend/src/prompts/csv_mapping.py` (new)
  - Prompt: "Given this CSV header and sample data, identify which columns are date, description, amount, balance"
  - Response: JSON column mapping

#### 4.4 Tests for Phase 4
- [x] Test: Reports include category breakdown from Layer 3 classification
- [x] Test: Reports fallback to account name when no classification exists
- [x] Test: ReportSnapshot generated and stored after report computation
- [x] Test: ReportSnapshot endpoint returns historical snapshots
- [x] Test: AI CSV parsing returns valid column mapping for unknown institutions
- [x] Test: Known institution CSV parsing still uses hardcoded parsers (no AI call)

---

## 📊 Acceptance Criteria Summary

| AC ID | Phase | Description |
|-------|-------|-------------|
| AC18.1.1 | 1 | Extraction prompt returns `suggested_category` and `category_confidence` |
| AC18.1.2 | 1 | `BankStatementTransaction` has `suggested_category` and `category_confidence` columns |
| AC18.1.3 | 1 | `RuleType.ML_MODEL` evaluates AI suggestion with confidence threshold ≥ 0.7 |
| AC18.1.4 | 1 | Classification priority: KEYWORD > REGEX > ML_MODEL > Uncategorized |
| AC18.1.5 | 1 | `create_entry_from_txn` reads classification before defaulting to Uncategorized |
| AC18.1.6 | 1 | Auto-created category accounts are user-scoped and correctly typed |
| AC18.2.1 | 2 | `CorrectionLog` model records original and corrected categories |
| AC18.2.2 | 2 | Corrections API records and retrieves correction stats |
| AC18.2.3 | 2 | Few-shot examples from corrections injected into extraction prompt |
| AC18.2.4 | 2 | Correction cache with 1-hour TTL |
| AC18.3.1 | 3 | `ai_semantic_score()` returns similarity for transaction description pairs |
| AC18.3.2 | 3 | Hybrid scoring: `0.7 * algorithmic + 0.3 * AI` for 60-84 range only |
| AC18.3.3 | 3 | Feature flag `enable_ai_reconciliation` controls AI scoring |
| AC18.4.1 | 4 | Reports read Layer 3 `TransactionClassification` for category breakdowns |
| AC18.4.2 | 4 | `ReportSnapshot` (Layer 4) generated and queryable via API |
| AC18.4.3 | 4 | AI CSV parsing handles unknown institutions as fallback |
| AC18.4.4 | 4 | Income statements include applied Layer 3 classification coverage |

### AC18.7: Evidence Graph Foundation

| AC ID | Phase | Description |
|-------|-------|-------------|
| AC18.7.1 | Evidence lineage | Evidence Graph SSOT defines nodes as auditable states, edges as transformation processes, allowed foundation node/edge fields, traversal direction, and append-only edge rules |
| AC18.7.2 | Evidence lineage | Alembic migration creates `evidence_nodes` and `evidence_edges` with user-scoped entity lookup and edge traversal indexes |
| AC18.7.3 | Evidence lineage | SQLAlchemy models expose `EvidenceNode` and `EvidenceEdge` with JSONB properties and user-owned isolation |
| AC18.7.4 | Evidence lineage | Evidence lineage service supports idempotent node and edge upsert keyed by user, entity identity, node kind, relation, and edge endpoints |
| AC18.7.5 | Evidence lineage | Evidence lineage service resolves entity nodes and traverses upstream and downstream paths only within the authenticated user scope |
| AC18.7.6 | Evidence lineage | Evidence lineage traversal enforces a default maximum depth and never walks unbounded graphs |
| AC18.7.7 | Evidence lineage | Evidence Graph foundation tests cover node creation, edge creation, duplicate upsert behavior, upstream traversal, downstream traversal, depth limit, and cross-user isolation |

### AC18.8: Evidence Graph Source-to-Report Integration

MECE task frame:

- Source capture: statement upload and parse create source document and extracted record nodes.
- Atomic fact integration: Layer 2 dual-write creates atomic fact nodes and `deduped_into` edges from extracted records.
- Ledger integration: statement posting creates ledger entry and ledger line nodes while preserving `JournalEntry.source_type/source_id`.
- Report integration: package traceability can resolve at least one report line through graph lineage back to source documents.
- Blocker handling: unsupported source IDs remain explicit blockers instead of fabricated source anchors.

Dependencies: AC18.7 Evidence Graph foundation and existing Layer 1/2, journal posting, and package traceability services. Out of scope: UI lineage panel, historical backfill, graph database adoption, and replacing every legacy traceability resolver in one change.

| AC ID | Phase | Description |
|-------|-------|-------------|
| AC18.8.1 | Evidence lineage integration | Statement upload and parse create a `source_document` node for the uploaded source and `extracted_record` nodes for parsed bank statement transactions linked by `parsed_into` edges |
| AC18.8.2 | Evidence lineage integration | Layer 2 dual-write creates `atomic_fact` nodes for atomic transactions and `deduped_into` edges from the parsed transaction records that produced them |
| AC18.8.3 | Evidence lineage integration | Journal posting creates `ledger_entry` and `ledger_line` nodes, links extracted or atomic transaction facts to the ledger entry with `posted_as`, and links the ledger entry to its lines with `contains` |
| AC18.8.4 | Evidence lineage integration | `GET /api/reports/package/traceability` can resolve at least one report line from ledger anchors through Evidence Graph lineage back to source document anchors |
| AC18.8.5 | Evidence lineage integration | Unknown or unsupported `JournalEntry.source_id` values produce explicit blocker codes and never fabricate statement, atomic, or document anchors |
| AC18.8.6 | Evidence lineage integration | Existing `JournalEntry.source_type/source_id` semantics remain backward-compatible while Evidence Graph writes add supplemental audit lineage |
| AC18.8.7 | Evidence lineage integration | Tests cover three end-to-end graph paths: source document downstream impact, bank statement transaction to ledger line, and report line to source document |

### AC18.9: Evidence Graph Navigation UX

MECE task frame:

- API contract: expose a generic user-scoped lineage endpoint by entity identity, node kind, direction, and bounded depth.
- DTO stability: return graph nodes and edges in a frontend-safe shape without exposing ORM internals or large payloads.
- Empty/blocker states: return explicit empty state for missing or unsupported graph anchors instead of invented links.
- Report entry point: add a package traceability panel that opens from report/package traceability rows.
- Product proof: cover report line to source document and source document to impacted ledger/report navigation.

Dependencies: AC18.7 Evidence Graph foundation and AC18.8 first production source-to-report graph integration. Out of scope: historical graph backfill, complex canvas visualization, graph database adoption, and replacing every legacy resolver.

| AC ID | Phase | Description |
|-------|-------|-------------|
| AC18.9.1 | Evidence navigation | An authenticated Evidence Graph lineage API resolves an owned graph node by `entity_type`, `entity_id`, and optional `node_kind` |
| AC18.9.2 | Evidence navigation | The lineage API supports upstream, downstream, and both-direction traversal with bounded depth and returns stable node and edge DTOs |
| AC18.9.3 | Evidence navigation | Missing, unsupported, or cross-user entity identities return explicit empty/blocker state and never fabricate source, ledger, or report anchors |
| AC18.9.4 | Evidence navigation UI | The report package traceability surface exposes a lineage panel from at least one report traceability row |
| AC18.9.5 | Evidence navigation UI | The lineage panel renders source document, extracted record, atomic fact, ledger entry, ledger line, and report-line anchors when present |
| AC18.9.6 | Evidence navigation proof | Tests cover report line to source document navigation and source document to impacted ledger/report navigation |

### Planned #733: Evidence Graph Lazy Materialization and Consistency Guardrails

MECE task frame:

- Write-through path: new business workflows continue to materialize Evidence Graph nodes and edges inside the same database transaction as the owning business facts.
- Lazy materialization path: lineage reads may repair missing historical graph anchors on demand, but only from deterministic relationships already present in source-of-truth tables.
- Consistency detection path: operator checks report graph drift without mutating accounting facts or deleting audit evidence.
- Blocker handling: incomplete, ambiguous, unsupported, or cross-user provenance remains explicit and user-scoped instead of guessed.
- Safety limits: request-time materialization is bounded by depth, write count, batch size, and user scope.

Dependencies: AC18.7 Evidence Graph foundation, AC18.8 source-to-report integration, and AC18.9 navigation API/UI. Out of scope: scheduled production auto-repair, probabilistic amount/date/description matching, graph database adoption, and mutating ledger balances or `JournalEntry.source_type/source_id`.

Implementation must register formal AC IDs with tests in the same PR that lands
code. The intended acceptance shape is:

- Evidence Graph SSOT defines graph as an audit projection, business tables as source of truth, and blocker taxonomy for drift states.
- New source-to-ledger workflows materialize graph nodes and edges in the same database transaction as their owning business facts.
- The lineage API attempts one bounded deterministic materialization pass when an owned anchor or required local path is missing for historical data.
- Lazy materialization is idempotent and only uses strong relationships such as owned source IDs, transaction lineage, and `journal_line.journal_entry_id`; it never infers links from fuzzy amount, date, or description similarity.
- An operator-safe dry-run detector reports missing graph nodes, graph nodes pointing to missing business entities, dangling edges, cross-user edges, incomplete lineage, and ambiguous or unsupported provenance.
- Detector and lazy repair never mutate accounting facts, report amounts, ledger balances, or legacy `JournalEntry.source_type/source_id` values.
- Tests cover request-time lazy repair, repeated-read idempotency, dry-run no-write behavior, cross-user blocking, unknown provenance blockers, dangling/orphan detection, and request-level write caps.

### AC18.6: Framework Measurement and Disclosure Suggestions

| AC ID | Phase | Description |
|-------|-------|-------------|
| AC18.6.1 | Framework reporting | AI-generated measurement or disclosure suggestions for US/HK personal report packages must remain structured, source-anchored, confidence-scored, and reviewed before EPIC-020 or EPIC-005 can treat them as trusted report inputs |

---

## 🚫 Out of Scope (v1)

- Custom ML model training (use prompt engineering + few-shot only)
- Real-time model fine-tuning
- Automated rule generation from corrections
- AI-powered anomaly detection (separate EPIC if needed)
- Multi-model A/B testing

---

## ⚠️ Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| AI category accuracy < 70% | Users lose trust, more corrections needed | Start with broad categories (14), not fine-grained. Measure accuracy before expanding. |
| OpenRouter API costs increase | Budget overrun | AI reconciliation behind feature flag. AI classification adds ~1 field to existing call (minimal cost). |
| Few-shot examples degrade quality | Worse suggestions over time | Limit to 10 most recent corrections. Monitor accuracy metrics. Reset mechanism available. |
| Layer 3→4 migration breaks reports | Existing reports break | Fallback: if no classification, use account name. Backward compatible. |

---

## 📏 Metrics & Monitoring

| Metric | Target | Measurement |
|--------|--------|-------------|
| AI category accuracy | ≥ 70% (Phase 1) | `corrections / total_classifications` |
| Uncategorized reduction | ≥ 50% decrease | Count of "Uncategorized" journal entries before/after |
| AI reconciliation improvement | +5% match rate in 60-84 range | Compare match rates with flag on/off |
| Feedback loop effectiveness | Accuracy improves 5%+ after 50 corrections | Track accuracy over time per user |
| API cost per extraction | < $0.01 increase | Monitor OpenRouter billing (category field adds ~50 tokens) |

---

## Personal Package Traceability Appendix

Issue [#572](https://github.com/wangzitian0/finance_report/issues/572) is the
EPIC-018-owned appendix surface for the personal financial-report package. It
keeps AI as provenance and explanation metadata only: report amounts still come
from deterministic ledger/reporting services, while the appendix exposes source
anchors, ledger anchors, review state, confidence tier, and completeness
warnings for package consumers.

Owned endpoint:
`GET /api/reports/package/traceability`

The appendix must disclose explicit `available`, `unavailable`, or
`not_applicable` anchor states instead of relying on missing fields. Trusted
report totals fail the package proof unless they have source and ledger anchors
or an explicit manual-input state, and existing
`source-ledger-report-traceability` macro proof ownership remains extended
rather than duplicated.

---

*Historical planning snapshot captured: March 2026*

---

## 🆕 Phase 5 — UI Gap Audit (April 2026): Confidence Hierarchy, AI Suggestion Review Queue, Feature-Flag UI & Audit Trail

**Origin**: UI gap audit against [Project Vision](../target.md) and `docs/ssot/source-type-priority.md` / `docs/ssot/confirmation-workflow.md`. Backend confidence hierarchy and `enable_ai_reconciliation` flag exist but are invisible to users — no badge, no review queue for AI suggestions, no in-product flag toggle, no audit trail.

### Acceptance Criteria — Phase 5 (Confidence & AI Suggestion UI)

- [x] **AC18.5.1** `<ConfidenceBadge />` component renders `TRUSTED` / `HIGH` / `MEDIUM` / `LOW` pill with consistent color tokens (green / blue / amber / gray) and tooltip explaining source-type priority
- [x] **AC18.5.2** ConfidenceBadge mounted on every transaction row in Stage 1 review, Stage 2 listing, and processing-account listing; reads `confidence_tier` from API response
- [x] **AC18.5.3** AI Suggestion Review Queue page `/review/ai-suggestions` lists pending AI classifications and AI reconciliation matches in score band 60-84 with `{transaction, suggested_category_or_match, ai_score, ai_reasoning}`
- [x] **AC18.5.4** Queue actions: `Accept`, `Reject`, `Edit-then-Accept`; each action calls `POST /api/ai/feedback` with `{suggestion_id, action, corrected_value?}` to feed the feedback loop
- [x] **AC18.5.5** Settings page `/settings/ai` exposes toggles for `enable_ai_reconciliation`, `enable_ai_classification`, persisted via `PATCH /api/users/me/settings`; toggle reflects backend feature-flag state on load
- [x] **AC18.5.6** Audit Trail panel on transaction detail page lists chronological `{timestamp, actor, action, old_value, new_value}` from `GET /api/transactions/{id}/audit`, including AI-applied changes labeled with actor `ai`
- [x] **AC18.5.7** Frontend tests: mount ConfidenceBadge for each tier; mount AI Suggestion Queue and assert Accept/Reject buttons render; mount Settings AI toggles and assert default state matches API

**Priority**: P0 — confidence visibility is a vision-critical trust signal; AI review queue is the human-in-the-loop hinge for the entire AI pipeline.
**Estimated effort**: 2 days ConfidenceBadge + integration • 4-5 days AI Suggestion Queue • 2 days Settings AI toggles • 2-3 days Audit Trail panel • 1-2 days frontend tests. **Total ~11-14 days frontend**, assumes Phase 1-4 backend endpoints from this EPIC are landed.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/source-type-priority.md](../ssot/source-type-priority.md) — confidence and source trust hierarchy used by AI-assisted flows.
- [../ssot/evidence-lineage.md](../ssot/evidence-lineage.md) — generic Evidence Graph contract for source-to-report audit lineage.
