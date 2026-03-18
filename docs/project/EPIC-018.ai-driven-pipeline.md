# EPIC-018: AI-Driven Data Pipeline

> **Status**: 🟡 Planned  
> **Phase**: 4 (AI Enhancement)  
> **Duration**: 4-7 weeks  
> **Priority**: P1 (High Priority - Parallel with EPIC-016)  
> **Dependencies**: EPIC-003 (Statement Parsing), EPIC-004 (Reconciliation Engine), EPIC-006 (AI Advisor), EPIC-013 (Statement Parsing V2)

---

## 🎯 Objective

Maximize AI utilization across the entire data pipeline from statement upload to financial reports. Currently, AI is only used in 2 of 7 pipeline stages (extraction and chat advisor). This EPIC extends AI into classification, reconciliation, journal entry creation, and feedback learning — transforming the pipeline from "AI extracts, human does everything else" to "AI handles what it can confidently, human reviews what it can't."

**Core Principle** (from vision.md): AI is a parsing and explanation layer, not a source of record. Confidence thresholds determine auto-accept vs. human review.

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
| 📊 **Accountant** | Data Integrity | AI suggestions are NEVER auto-posted. Must pass through review queue. Confidence thresholds: ≥85 auto-accept, 60-84 review, <60 flag. |
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

---

## ✅ Task Checklist

### Phase 1: AI-Powered Classification — 1-2 weeks (Highest ROI)

#### 1.1 Extraction Prompt Enhancement
- [ ] Add `suggested_category` and `category_confidence` fields to extraction prompt
  - File: `apps/backend/src/prompts/statement.py`
  - Categories: Food & Dining, Transport, Shopping, Utilities, Salary, Transfer, Investment, Insurance, Rent, Healthcare, Entertainment, Education, Subscriptions, Other
  - Confidence: 0.0-1.0 float returned by AI
- [ ] Add `suggested_category` VARCHAR(100) and `category_confidence` DECIMAL(3,2) columns to `BankStatementTransaction`
  - File: `apps/backend/src/models/statement.py`
  - Migration: Alembic migration with nullable columns (backward compatible)
- [ ] Update extraction service to parse and persist AI-returned category fields
  - File: `apps/backend/src/services/extraction.py`
  - Graceful fallback: if AI omits category, set `suggested_category=NULL`, `category_confidence=0.0`

#### 1.2 Classification Service: Implement ML_MODEL Rule Type
- [ ] Implement `RuleType.ML_MODEL` match logic in `ClassificationService.evaluate_rule()`
  - File: `apps/backend/src/services/classification.py`
  - Logic: Read `suggested_category` from `BankStatementTransaction` → apply confidence threshold
  - Threshold: `category_confidence ≥ 0.7` → accept AI suggestion
  - Currently 91 lines, `ML_MODEL` case returns `False` → make it functional
- [ ] Add `classify_with_ai()` method that queries extraction results before falling back to rules
  - Priority: KEYWORD_MATCH → REGEX_MATCH → ML_MODEL (AI suggestion) → Uncategorized
  - This preserves existing user-defined rules as highest priority

#### 1.3 Journal Entry: Read Classification Before Uncategorized Fallback
- [ ] Modify `create_entry_from_txn()` to check classification results before defaulting to Uncategorized
  - File: `apps/backend/src/services/review_queue.py` (lines 264-359)
  - Current: `get_or_create_account(db, name="Income - Uncategorized")` / `"Expense - Uncategorized"`
  - Target: Check `TransactionClassification` for the transaction → use classified account if exists → fallback to Uncategorized
  - Account naming: `"Income - {category}"` or `"Expense - {category}"` (e.g., `"Expense - Food & Dining"`)
- [ ] Ensure `get_or_create_account()` creates accounts on-demand for new AI-suggested categories
  - Auto-created accounts must be: user-scoped, correct type (Income/Expense), correct currency

#### 1.4 Tests for Phase 1
- [ ] Test: AI extraction includes `suggested_category` and `category_confidence` in response
- [ ] Test: Missing AI category fields gracefully default to NULL/0.0
- [ ] Test: `ML_MODEL` rule type returns True when confidence ≥ 0.7
- [ ] Test: `ML_MODEL` rule type returns False when confidence < 0.7
- [ ] Test: Classification priority: KEYWORD > REGEX > ML_MODEL > Uncategorized
- [ ] Test: `create_entry_from_txn` uses classified category when available
- [ ] Test: `create_entry_from_txn` falls back to Uncategorized when no classification exists
- [ ] Test: Auto-created category accounts are correct type and user-scoped

---

### Phase 2: Feedback Learning Loop — 1 week

#### 2.1 Correction Log Model
- [ ] Create `CorrectionLog` model
  - File: `apps/backend/src/models/correction.py` (new)
  - Fields: `id`, `user_id`, `transaction_id`, `original_category`, `corrected_category`, `original_account_id`, `corrected_account_id`, `created_at`
  - Links to: `BankStatementTransaction`, `Account`, `User`
  - Purpose: Track every user correction for few-shot learning
- [ ] Alembic migration for `correction_log` table

#### 2.2 Correction Recording API
- [ ] `POST /api/corrections` — Record a user correction
  - Input: `transaction_id`, `corrected_category`, `corrected_account_id`
  - Auto-fills `original_category` from transaction's current classification
  - Returns: correction record
- [ ] `GET /api/corrections/stats` — Get correction statistics
  - Return: top N corrected categories, accuracy rate per category, total corrections
  - Use for monitoring AI quality over time

#### 2.3 Few-Shot Prompt Injection
- [ ] Query `CorrectionLog` for user's recent corrections (last 50)
  - Group by `original_category → corrected_category` pattern
  - Inject as few-shot examples into extraction prompt
  - Format: "Previously, transactions like '{description}' were categorized as '{corrected_category}'"
- [ ] Update `apps/backend/src/prompts/statement.py` to accept correction examples
  - Add `correction_examples: list[dict]` parameter to prompt builder
  - Inject up to 10 most relevant corrections as few-shot context
- [ ] Add cache for correction examples (per user, 1-hour TTL)
  - Avoid querying correction log on every extraction call

#### 2.4 Tests for Phase 2
- [ ] Test: Correction log records original and corrected categories
- [ ] Test: Correction stats aggregate correctly
- [ ] Test: Few-shot examples injected into extraction prompt
- [ ] Test: Prompt with corrections produces different output than without (mock test)
- [ ] Test: Correction cache invalidates after TTL
- [ ] Test: Empty correction log produces standard prompt (no few-shot)

---

### Phase 3: AI-Assisted Reconciliation — 1-2 weeks

#### 3.1 AI Semantic Scoring
- [ ] Add `ai_semantic_score()` method to reconciliation service
  - File: `apps/backend/src/services/reconciliation.py`
  - Trigger: Only for candidates scoring 60-84 (review queue range)
  - Input: Transaction description pair (bank statement + journal entry memo)
  - Output: Semantic similarity score (0-100) from AI
  - Cost control: Only called for review-queue candidates, not all matches
- [ ] Create `apps/backend/src/prompts/reconciliation.py` (new)
  - Prompt: "Given these two transaction descriptions, rate their semantic similarity (0-100)"
  - Include context: date proximity, amount match, account info
  - Response format: JSON with `similarity_score` and `reasoning`

#### 3.2 Hybrid Scoring Integration
- [ ] Modify `calculate_match_score()` to incorporate AI semantic score
  - Current: Pure algorithmic (date, amount, description fuzzy match)
  - New: `final_score = 0.7 * algorithmic_score + 0.3 * ai_semantic_score`
  - Only applies when algorithmic score is in 60-84 range
  - Scores outside that range remain unchanged (≥85 auto-accept, <60 unmatched)
- [ ] Add feature flag: `enable_ai_reconciliation` in `config.py`
  - Default: `False` (opt-in to avoid unexpected API costs)
  - When disabled: existing pure-algorithmic behavior unchanged

#### 3.3 Tests for Phase 3
- [ ] Test: `ai_semantic_score()` returns score for matching descriptions
- [ ] Test: `ai_semantic_score()` returns low score for unrelated descriptions
- [ ] Test: Hybrid scoring only triggers for 60-84 range candidates
- [ ] Test: Feature flag disables AI scoring when False
- [ ] Test: Algorithmic scores ≥85 and <60 bypass AI scoring entirely
- [ ] Test: Final score correctly weights algorithmic (0.7) and AI (0.3)

---

### Phase 4: Pipeline Integration & Report Fix — 1-2 weeks

#### 4.1 Reports Read Layer 3 Classification
- [ ] Modify `reporting.py` to read `TransactionClassification` (Layer 3) instead of raw `JournalLine`
  - File: `apps/backend/src/services/reporting.py`
  - Current: Reports read `JournalEntry` → `JournalLine` directly, ignoring Layer 3
  - Target: Reports query `TransactionClassification` for category breakdowns
  - Fallback: If transaction has no classification, use account name as category (backward compatible)
- [ ] Add category breakdown to Income Statement
  - Group expenses/income by classified category
  - Show: Category, Amount, % of Total
  - Use `TransactionClassification.assigned_category` field

#### 4.2 ReportSnapshot (Layer 4) Utilization
- [ ] Implement `ReportSnapshot` generation
  - File: `apps/backend/src/models/layer4.py` (model exists but unused)
  - Generate snapshots after report computation
  - Store: report type, date range, computed data (JSONB), generated_at
  - Enable historical comparison: "This month vs last month" reports
- [ ] Add `GET /api/reports/{type}/snapshots` endpoint
  - List available snapshots for a report type
  - Enable time-series trend analysis

#### 4.3 CSV Parsing via AI (Remove Hardcoding)
- [ ] Add AI-powered CSV parsing as fallback for unknown institutions
  - Current: CSV parsing is hardcoded per institution (DBS, Wise, etc.)
  - New: When institution is unknown, send CSV header + sample rows to AI
  - AI returns: column mapping (date, description, amount, balance)
  - Preserve existing hardcoded parsers for known institutions (they're faster and free)
- [ ] Create `apps/backend/src/prompts/csv_mapping.py` (new)
  - Prompt: "Given this CSV header and sample data, identify which columns are date, description, amount, balance"
  - Response: JSON column mapping

#### 4.4 Tests for Phase 4
- [ ] Test: Reports include category breakdown from Layer 3 classification
- [ ] Test: Reports fallback to account name when no classification exists
- [ ] Test: ReportSnapshot generated and stored after report computation
- [ ] Test: ReportSnapshot endpoint returns historical snapshots
- [ ] Test: AI CSV parsing returns valid column mapping for unknown institutions
- [ ] Test: Known institution CSV parsing still uses hardcoded parsers (no AI call)

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

*Last updated: March 2026*