# EPIC-004: Reconciliation Engine & Matching

> **Status**: ⏳ Pending  
> **Phase**: 3  
> **Duration**: 5 weeks  
> **Dependencies**: EPIC-003  

---

## 🎯 Objective

Automatically match bank transactions with journal entries, implementing intelligent reconciliation and review queue, achieving ≥95% automatic matching accuracy.

**Core Rules**:
```
≥ 85 points  → Auto-accept
60-84 points → Review queue
< 60 points  → Unmatched
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🔗 **Reconciler** | Matching algorithm | Multi-dimensional weighted scoring, adjustable thresholds, supports one-to-many/many-to-one |
| 🏗️ **Architect** | System design | Independent matching engine service, supports batch processing and incremental matching |
| 📊 **Accountant** | Business logic | Account type combinations must follow accounting logic (e.g., salary = Bank + Income) |
| 💻 **Developer** | Performance requirements | 10,000 transactions matched in < 10s, supports parallel processing |
| 🧪 **Tester** | Accuracy verification | False positive rate < 0.5%, false negative rate < 2% |
| 📋 **PM** | User experience | Efficient and user-friendly review queue, batch operation support |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `ReconciliationMatch` model
  - `bank_txn_id` - Bank transaction ID
  - `journal_entry_ids` - Associated journal entry IDs (supports multiple)
  - `match_score` - Composite score (0-100)
  - `score_breakdown` - Individual dimension scores (JSONB)
  - `status` - Status (auto_accepted/pending_review/accepted/rejected)
- [ ] Alembic migration script
- [ ] Status update trigger (updates JournalEntry and BankStatementTransaction status)

### Matching Algorithm (Backend)

- [ ] `services/reconciliation.py` - Reconciliation engine
  - [ ] `calculate_match_score()` - Composite scoring
  - [ ] `find_candidates()` - Find candidate journal entries
  - [ ] `execute_matching()` - Batch matching execution
  - [ ] `auto_accept()` - Auto-accept logic
- [ ] Scoring dimension implementation
  - [ ] `score_amount()` - Amount matching (40%)
  - [ ] `score_date()` - Date proximity (25%)
  - [ ] `score_description()` - Description similarity (20%)
  - [ ] `score_business_logic()` - Business logic validation (10%)
  - [ ] `score_pattern()` - Historical pattern (5%)
- [ ] Special scenario handling
  - [ ] One-to-many matching (1 bank txn → multiple journal entries)
  - [ ] Many-to-one matching (multiple bank txns → 1 journal entry)
  - [ ] Cross-period matching (month-end/month-start)
  - [ ] Fee splitting

### Review Queue (Backend)

- [ ] `services/review_queue.py` - Review queue management
  - [ ] `get_pending_items()` - Get pending items (pagination, sorting)
  - [ ] `accept_match()` - Accept match
  - [ ] `reject_match()` - Reject match
  - [ ] `batch_accept()` - Batch accept
  - [ ] `create_entry_from_txn()` - Create journal entry from transaction

### Anomaly Detection (Backend)

- [ ] `services/anomaly.py` - Anomaly detection
  - [ ] Amount anomaly (> 10x monthly average)
  - [ ] Frequency anomaly (same merchant > 5 transactions/day)
  - [ ] Time anomaly (large amounts during non-business hours)
  - [ ] New merchant flagging

### API Endpoints (Backend)

- [ ] `POST /api/reconciliation/run` - Execute reconciliation matching
- [ ] `GET /api/reconciliation/matches` - Match results list
- [ ] `GET /api/reconciliation/pending` - Pending review queue
- [ ] `POST /api/reconciliation/matches/{id}/accept` - Accept match
- [ ] `POST /api/reconciliation/matches/{id}/reject` - Reject match
- [ ] `POST /api/reconciliation/batch-accept` - Batch accept
- [ ] `GET /api/reconciliation/stats` - Reconciliation statistics
- [ ] `GET /api/reconciliation/unmatched` - Unmatched transactions

### Frontend UI (Frontend)

- [ ] `/reconciliation` - Reconciliation workbench
  - [ ] Reconciliation overview (match rate, unmatched count)
  - [ ] Pending review list (sorting, filtering)
  - [ ] Match details (score breakdown, candidate entries)
  - [ ] Accept/reject operations
  - [ ] Batch operation toolbar
- [ ] `/reconciliation/unmatched` - Unmatched handling
  - [ ] Unmatched transaction list
  - [ ] Manual journal entry creation
  - [ ] Ignore/flag functionality
- [ ] Visualization
  - [ ] Reconciliation progress bar
  - [ ] Match score distribution chart
  - [ ] Anomalous transaction highlighting

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Auto-match accuracy ≥ 95%** | Real data test set validation | 🔴 Critical |
| **False positive rate < 0.5%** | Manual audit of 100 transactions | 🔴 Critical |
| **False negative rate < 2%** | Ratio of should-match but unmatched | 🔴 Critical |
| Configurable thresholds | Parameterized design | Required |
| One-to-many matching support | Test scenario validation | Required |
| Batch process 10,000 txns < 10s | Performance testing | Required |
| Post-match status correctly updated | JournalEntry/BankTxn status check | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Auto-match rate > 70% | Reduce manual review | ⏳ |
| Review queue avg processing < 30s/txn | User behavior statistics | ⏳ |
| Anomaly detection recall > 95% | Flagged anomaly coverage | ⏳ |
| ML-based weight tuning | Optimize based on historical data | ⏳ |
| Visual matching rule configuration | Admin interface | ⏳ |

### 🚫 Not Acceptable Signals

- False positive rate > 2% (severely pollutes ledger)
- Accuracy < 90% (defeats automation purpose)
- Performance timeout (batch processing > 60s)
- Severe review queue backlog
- Users cannot understand match scores

---

## 🧪 Test Scenarios

### Matching Algorithm Tests (Required)

```python
# Exact matching
def test_exact_match_high_score():
    """Amount, date, description fully match → score ≥ 95"""

def test_fuzzy_date_match():
    """Date difference 2 days → score 85-94"""

def test_amount_tolerance():
    """Amount difference 0.05 (fee) → score 80-90"""

# Multiple matching
def test_one_to_many_match():
    """1 repayment 1000 = 3 expenses (400+350+250)"""

def test_many_to_one_match():
    """3 small transactions = 1 batch payment"""

# Edge cases
def test_cross_month_match():
    """1/31 outgoing → 2/1 incoming, should match"""

def test_no_match_low_score():
    """Completely unrelated → score < 60"""
```

### Business Logic Tests (Required)

```python
def test_salary_pattern():
    """Salary deposit: Bank DEBIT + Income CREDIT"""

def test_credit_card_pattern():
    """Credit card payment: Liability DEBIT + Bank CREDIT"""

def test_invalid_pattern_penalty():
    """Invalid combination (e.g., Income + Expense) should reduce score"""
```

### Performance Tests (Required)

```python
def test_batch_10000_transactions():
    """10,000 transactions matched in < 10s"""

def test_concurrent_matching():
    """Concurrent reconciliation without data race"""
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - ReconciliationMatch table
- [reconciliation.md](../ssot/reconciliation.md) - Reconciliation rules
- [reconciler.md](../../.claude/skills/reconciler.md) - Matching algorithm design

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/reconciliation.py`
- [ ] `apps/backend/src/services/reconciliation.py`
- [ ] `apps/backend/src/services/review_queue.py`
- [ ] `apps/backend/src/services/anomaly.py`
- [ ] `apps/backend/src/routers/reconciliation.py`
- [ ] `apps/frontend/app/reconciliation/page.tsx`
- [ ] Update `docs/ssot/reconciliation.md` (algorithm documentation)
- [ ] Reconciliation accuracy report

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| ML-based weight auto-tuning | P2 | v2.0 |
| Multi-currency matching | P2 | After EPIC-005 |
| Real-time matching (match on txn import) | P3 | Future iteration |

---

## Issues & Gaps

- [ ] SSOT defines scoring weights/thresholds in `config/reconciliation.yaml`, but EPIC-004 does not include this config deliverable, so weights may become hardcoded.
- [ ] EPIC-004 introduces new tables and dependencies (ReconciliationRule, MerchantPattern, transaction_embeddings, pgvector) that are not defined in `docs/ssot/schema.md`; SSOT must be updated before implementation.
- [ ] Dual-layer versioned `ReconciliationMatch` (version/superseded) is not reflected in SSOT schema or ER model; schema alignment is required.

---

## ❓ Q&A (Clarification Required)

### Q1: Are matching thresholds adjustable?
> **Question**: Are the 85/60 thresholds fixed, or can users adjust them?

**✅ Your Answer**: A - Global fixed thresholds, consider optimization after collecting real data

**Decision**: Use fixed thresholds in v1.0
- `AUTO_ACCEPT_THRESHOLD = 85`
- `REVIEW_QUEUE_THRESHOLD = 60`
- These values are configured in environment variables (for future adjustment)
- Analyze accuracy and user feedback using MVP phase real matching data
- Consider dynamic thresholds or account-type-specific configuration in v1.5+

### Q2: Unmatched transaction handling workflow
> **Question**: How to handle unmatched transactions (score < 60)?

**✅ Your Answer**: C - AI-recommended journal entry templates. These rules are time-sensitive and may be effective within specific periods.

**Decision**: AI-driven journal entry recommendations + time-aware rules
- **Unmatched transaction handling workflow**:
  1. When transaction match score < 60, trigger `suggest_journal_entry()` service
  2. Generate AI recommendations based on transaction info (amount, description, date, account, etc.)
  3. AI recommendations include:
     - Suggested account combinations (e.g., "for expenses use Expense + Liability")
     - Suggested amount splits (e.g., "principal 2000 + interest 50")
     - Suggested event types (salary, card_payment, transfer, fee, etc.)
  4. User can accept recommendation with one click, or modify and manually create
  
- **Time-aware rule mechanism**:
  - Establish `ReconciliationRule` table:
    ```
    id, user_id, rule_name, description, 
    conditions (JSONB), actions (JSONB),
    effective_from, effective_to, priority, is_enabled
    ```
  - Rule example:
    ```json
    {
      "name": "Salary deposit rule (Jan-Mar only)",
      "conditions": {
        "description_contains": ["SALARY", "EMPLOYER"],
        "amount_range": [4000, 6000],
        "date_in_months": [1, 2, 3]
      },
      "actions": {
        "account_debit": "Bank Main",
        "account_credit": "Income Salary",
        "auto_match_boost": 20
      },
      "effective_from": "2025-01-01",
      "effective_to": "2025-03-31"
    }
    ```
  - During reconciliation, load active rules within effective period to enhance AI recommendation accuracy
  - Users can customize rules (UI provides rule editor)
  - System learns from user's historical acceptance of recommendations, gradually improving recommendation quality

### Q3: Duplicate matching detection
> **Question**: Once a transaction is matched, is it allowed to modify or re-match?

**✅ Your Answer**: C + Advanced architecture - Use two-layer data model:
- Raw layer (Account Event): Preserve complete history, immutable
- Analysis layer (Ontology Event): Support multi-version mapping, 1:N and N:1 relationships

**Decision**: Dual-layer event model - Immutable raw layer + Mutable analysis layer

**Data Model**:
```
BankStatementTransaction (Raw Layer)
├─ id (UUID)
├─ statement_id
├─ txn_date, amount, direction, description
├─ created_at (IMMUTABLE)
└─ status: pending/matched/unmatched

ReconciliationMatch v1 (Analysis Layer, Multi-version)
├─ id (UUID)
├─ bank_txn_id (FK)
├─ journal_entry_ids[] (supports multiple)
├─ match_score
├─ version (int)
├─ created_at
├─ superseded_by_id (points to next version)
└─ status: active/superseded/rejected

JournalEntry (Raw Layer)
├─ id (UUID)
├─ entry_date, memo
├─ created_at (IMMUTABLE)
└─ matched_by_id[] (points to currently active ReconciliationMatch)
```

**Matching workflow** (supports version evolution):
1. New match creates `ReconciliationMatch v1`
2. When user modifies match:
   - Create new version `ReconciliationMatch v2` (not overwrite v1)
   - v1.superseded_by_id = v2.id
   - v1.status = superseded
3. When user splits one transaction into multiple entries:
   - Original `ReconciliationMatch v1` is superseded (many-to-one → one-to-many)
   - Create multiple new `ReconciliationMatch` records, each associated with different entry
4. When user merges multiple transactions into one entry:
   - Multiple original ReconciliationMatch marked as superseded
   - Create new version linking all transactions

**Query rules**:
- Frontend displays current active matches: status='active' AND superseded_by_id IS NULL
- Reports count only active matches
- Audit queries can view complete version history

**Benefits**:
- ✅ Original data never lost (financial compliance)
- ✅ Supports arbitrary N:M matching relationships
- ✅ Complete modification audit trail
- ✅ Supports rule evolution (same transaction classified differently in different periods)

### Q4: Batch operation safety restrictions
> **Question**: Does batch acceptance require additional verification?

**✅ Your Answer**: C - Only allow batch accept for high-score items (≥ 80), low-score items require individual review

**Decision**: Tiered batch operation strategy
- **High-score fast track** (score ≥ 80):
  - Support one-click batch acceptance of all high-score items
  - Can batch operate after filtering by date range, amount range
  - UI displays total count and total amount to be confirmed
- **Low-score individual review** (60 ≤ score < 80):
  - Requires individual review, no batch operations
  - Frontend list only allows single accept/reject
  - Forces users to view each transaction's details
- **Batch operation confirmation dialog**:
  - Modal displays: count to be batch confirmed, total amount, date range
  - Shows examples (first 5 items)
  - User must check "I have reviewed the above information" to confirm
- **Operation audit**:
  - Each batch operation records operator, timestamp, confirmation count
  - Supports batch undo (can only undo batch confirmations within 24 hours)

### Q5: Historical pattern learning
> **Question**: Should the algorithm adjust based on user's historical matching behavior?

**✅ Your Answer**: B + embedding - Simple rule learning, use embedding for similarity matching

**Decision**: Embedding-driven intelligent matching (simple and efficient)

**Implementation approach**:
- **Embedding layer** (using open-source model, e.g., sentence-transformers):
  - Generate embedding for each BankStatementTransaction description
  - Generate embedding for each JournalEntry memo
  - Calculate cosine similarity between them as "description similarity" score enhancement
  
- **Merchant pattern learning** (simple rules):
  - Maintain `MerchantPattern` table:
    ```
    merchant_name, canonical_merchant,
    preferred_account_id, confidence,
    last_matched_at, match_count
    ```
  - Update pattern when user confirms match:
    ```
    IF MERCHANT exists:
      UPDATE match_count, confidence
    ELSE:
      INSERT new merchant pattern
    ```
  - Next time encountering same merchant transaction, skip low-score candidates, prioritize historical accounts
  
- **Temporal pattern recognition** (subscription transactions):
  - Identify fixed-interval transactions (e.g., same day each month, fixed amount)
  - Apply bonus score (e.g., +10 points)
  - Example: Monthly 25th, 500 SGD rent
  
- **Integration**:
  ```
  score = 40% amount_match 
        + 25% date_match 
        + 20% embedding_similarity  // NEW
        + 10% business_logic 
        + 5% pattern_bonus        // merchant pattern + temporal pattern
  ```

**Database tables**:
```sql
-- Merchant pattern learning
CREATE TABLE merchant_patterns (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    merchant_name VARCHAR(255),
    canonical_merchant VARCHAR(255),
    preferred_account_id UUID,
    confidence DECIMAL(3,2),  -- 0-1
    match_count INT,
    last_matched_at TIMESTAMP
);

-- Embedding cache
CREATE TABLE transaction_embeddings (
    id UUID PRIMARY KEY,
    source_type ENUM ('bank_txn', 'journal_entry'),
    source_id UUID,
    embedding VECTOR(384),  -- pgvector extension
    created_at TIMESTAMP
);
```

**Benefits**:
- ✅ Simple, no complex ML framework needed
- ✅ Solves most pattern recognition problems (merchant identification, similar transactions)
- ✅ Can be incrementally optimized (start with fixed embedding, fine-tune later)
- ✅ Multilingual support (embedding models typically support multiple languages)
- ✅ Good performance (vector similarity computation is fast)

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data model + Basic matching algorithm | 16h |
| Week 2 | Scoring dimensions + Special scenarios | 20h |
| Week 3 | Review queue + Anomaly detection | 16h |
| Week 4 | Frontend UI + Algorithm tuning + Testing | 20h |
| Week 5 | Embedding integration + Time-aware rules + Dual-layer model | 16h |

**Total estimate**: 88 hours (5 weeks)
