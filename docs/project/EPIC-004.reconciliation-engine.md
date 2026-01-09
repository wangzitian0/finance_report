# EPIC-004: Reconciliation Engine & Matching

> **Status**: ⏳ Pending 
> **Phase**: 3 
> **Duration**: 5 weeks 
> **Dependencies**: EPIC-003 

---

## 🎯 Objective

matchbanktransactionandjournal entry, implementation can for andqueue, to ≥95% matchaccurate. 

** then **:
```
≥ 85 minutes → accept
60-84 minutes → queue
< 60 minutes → match
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🔗 **Reconciler** | match | dimensionminutes, threshold can , support for / for |
| 🏗️ **Architect** | design | matchservice, supportprocessandmatch |
| 📊 **Accountant** | | accountclassRequiredcomply will logic (such as =Bank+Income) |
| 💻 **Developer** | can need to | 10,000 transactionmatch < 10s, supportprocess |
| 🧪 **Tester** | accuratevalidate | match < 0.5%, match < 2% |
| 📋 **PM** | use body | queuehigh use, support |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `ReconciliationMatch` model
 - `bank_txn_id` - banktransaction ID
 - `journal_entry_ids` - journal entry ID (support)
 - `match_score` - minutes (0-100)
 - `score_breakdown` - eachdimensionminutes (JSONB)
 - `status` - Status (auto_accepted/pending_review/accepted/rejected)
- [ ] Alembic migration
- [ ] Statusupdatetrigger (update JournalEntry and BankStatementTransaction Status)

### match (Backend)

- [ ] `services/reconciliation.py` - for 
 - [ ] `calculate_match_score()` - minutes
 - [ ] `find_candidates()` - journal entry
 - [ ] `execute_matching()` - match
 - [ ] `auto_accept()` - acceptlogic
- [ ] minutesdimensionimplementation
 - [ ] `score_amount()` - amountmatch (40%)
 - [ ] `score_date()` - date (25%)
 - [ ] `score_description()` - (20%)
 - [ ] `score_business_logic()` - (10%)
 - [ ] `score_pattern()` - pattern (5%)
- [ ] process
 - [ ] for match (1 transaction → journal entry)
 - [ ] for match (transaction → 1 journal entry)
 - [ ] match (month/month)
 - [ ] minutes

### queue (Backend)

- [ ] `services/review_queue.py` - queue
 - [ ] `get_pending_items()` - get (pagination, sort)
 - [ ] `accept_match()` - confirmationmatch
 - [ ] `reject_match()` - rejectmatch
 - [ ] `batch_accept()` - confirmation
 - [ ] `create_entry_from_txn()` - from transactioncreatejournal entry

### exception (Backend)

- [ ] `services/anomaly.py` - exception
 - [ ] amountexception (> 10x month)
 - [ ] exception ( > 5 /days)
 - [ ] timeexception (non- time)
 - [ ] 

### API endpoint (Backend)

- [ ] `POST /api/reconciliation/run` - for match
- [ ] `GET /api/reconciliation/matches` - matchtable
- [ ] `GET /api/reconciliation/pending` - queue
- [ ] `POST /api/reconciliation/matches/{id}/accept` - confirmationmatch
- [ ] `POST /api/reconciliation/matches/{id}/reject` - rejectmatch
- [ ] `POST /api/reconciliation/batch-accept` - confirmation
- [ ] `GET /api/reconciliation/stats` - for statistics
- [ ] `GET /api/reconciliation/unmatched` - not yet matchtransaction

### Frontend (Frontend)

- [ ] `/reconciliation` - for 
 - [ ] for (match, not yet match)
 - [ ] table (sort, )
 - [ ] match (minutes, journal entry)
 - [ ] confirmation/reject
 - [ ] 
- [ ] `/reconciliation/unmatched` - not yet matchprocess
 - [ ] not yet matchtransactiontable
 - [ ] createjournal entry
 - [ ] / can 
- [ ] can 
 - [ ] for 
 - [ ] matchminutesminutes
 - [ ] exceptionhigh

---

## 📏 good not good standard

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **matchaccurate ≥ 95%** | testvalidate | 🔴 critical |
| **match < 0.5%** | 100 | 🔴 critical |
| **match < 2%** | should match but not yet match compare | 🔴 critical |
| threshold can configuration | parameterdesign | Required |
| for matchsupport | Test Scenariosvalidate | Required |
| process 10,000 < 10s | can test | Required |
| matchStatuscorrectupdate | JournalEntry/BankTxn Statuscheck | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| match > 70% | decrease | ⏳ |
| queueprocesstime < 30s/ | use as/for statistics | ⏳ |
| exception > 95% | exceptioncoverage of | ⏳ |
| good | in/at optimization | ⏳ |
| match then can configuration | | ⏳ |

### 🚫 Not Acceptable Signals

- match > 2% ()
- accurate < 90% ()
- can timeout (process > 60s)
- queue
- use no/none matchminutes

---

## 🧪 Test Scenarios

### matchtest (Required)

```python
# precisematch
def test_exact_match_high_score():
 """amount, date, Completematch → minutes ≥ 95"""

def test_fuzzy_date_match():
 """date 2 days → minutes 85-94"""

def test_amount_tolerance():
 """amount 0.05 () → minutes 80-90"""

# match
def test_one_to_many_match():
 """1 1000 = 3 (400+350+250)"""

def test_many_to_one_match():
 """3 transaction = 1 """

# boundary
def test_cross_month_match():
 """1/31 → 2/1 , match"""

def test_no_match_low_score():
 """Complete → minutes < 60"""
```

### logictest (Required)

```python
def test_salary_pattern():
 """:Bank DEBIT + Income CREDIT"""

def test_credit_card_pattern():
 """:Liability DEBIT + Bank CREDIT"""

def test_invalid_pattern_penalty():
 """ (such as Income + Expense)minutes"""
```

### can test (Required)

```python
def test_batch_10000_transactions():
 """10,000 transactionmatch < 10s"""

def test_concurrent_matching():
 """reconciliation"""
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - ReconciliationMatch table
- [reconciliation.md](../ssot/reconciliation.md) - for then 
- [reconciler.md](../../.claude/skills/reconciler.md) - matchdesign

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/reconciliation.py`
- [ ] `apps/backend/src/services/reconciliation.py`
- [ ] `apps/backend/src/services/review_queue.py`
- [ ] `apps/backend/src/services/anomaly.py`
- [ ] `apps/backend/src/routers/reconciliation.py`
- [ ] `apps/frontend/app/reconciliation/page.tsx`
- [ ] update `docs/ssot/reconciliation.md` ()
- [ ] for accurate

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| ML good | P2 | v2.0 |
| match | P2 | EPIC-005 |
| match (transactionthat ismatch) | P3 | |

---

## ❓ Q&A (Clarification Required)

### Q1: matchthreshold is no can 
> **Question**: 85/60 threshold is , still/also is use can with ? 

**✅ Your Answer**: A - threshold, etc. have/has again optimization

**Decision**: usethreshold
- `AUTO_ACCEPT_THRESHOLD = 85`
- `REVIEW_QUEUE_THRESHOLD = 60`
- thisconfiguration in/at variable in ( in/at )
- use MVP phasematch, analysisaccurateand use feedback
- v1.5+ again dynamicthresholdoraccountclassconfiguration

### Q2: not yet matchtransaction processprocess
> **Question**: not yet matchtransaction (minutes < 60) such as process? 

**✅ Your Answer**: C - AI Recommendedjournal entry. this then is time, can can in/at . 

**Decision**: AI journal entryRecommended + time then 
- ** not yet matchtransactionprocessprocess**:
 1. transactionmatchminutes < 60 , trigger `suggest_journal_entry()` service
 2. transaction (amount, , date, account etc.)generate AI Recommended
 3. AI Recommendedcontain:
 - recommendationaccount (such as " use Expense + Liability")
 - recommendationamountminutes (such as " 2000 + 50")
 - recommendationeventclass (salary, card_payment, transfer, fee etc.)
 4. use can acceptRecommended, ormodifycreate
 
- **time then **:
 - `ReconciliationRule` table:
 ```
 id, user_id, rule_name, description, 
 conditions (JSONB), actions (JSONB),
 effective_from, effective_to, priority, is_enabled
 ```
 - then sample:
 ```json
 {
 "name": "then ( 1-3 month)",
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
 - for , have/has then, AI Recommended accurate
 - use can custom then (UI then edit)
 - use accept Recommended, improveRecommendedquality

### Q3: match
> **Question**: transaction already match, is no allowmodifyormatch? 

**✅ Your Answer**: C + higharchitecture - use Data Model:
- (Account Event):complete, not can modify
- analysis (Ontology Event):supportversion, 1:N and N:1 

**Decision**: eventmodel - not can + can analysis

**Data Model**:
```
BankStatementTransaction ()
├─ id (UUID)
├─ statement_id
├─ txn_date, amount, direction, description
├─ created_at (IMMUTABLE)
└─ status: pending/matched/unmatched

ReconciliationMatch v1 (analysis, version)
├─ id (UUID)
├─ bank_txn_id (FK)
├─ journal_entry_ids[] (support)
├─ match_score
├─ version (int)
├─ created_at
├─ superseded_by_id (version)
└─ status: active/superseded/rejected

JournalEntry ()
├─ id (UUID)
├─ entry_date, memo
├─ created_at (IMMUTABLE)
└─ matched_by_id[] ( ReconciliationMatch)
```

**matchprocess** (supportversion):
1. matchcreate `ReconciliationMatch v1`
2. use modifymatch:
 - createversion `ReconciliationMatch v2` (not is coverage of v1)
 - v1.superseded_by_id = v2.id
 - v1.status = superseded
3. use will transactionminutes as/for journal entry:
 - `ReconciliationMatch v1` ( for → for )
 - create `ReconciliationMatch` , each not journal entry
4. use transaction to journal entry:
 - ReconciliationMatch as/for superseded
 - createversion have/has transaction

**query then **:
- Frontend displaysmatch:status='active' superseded_by_id IS NULL
- reportcalculatecountedmatch
- query can completeversion

**good**:
- ✅ not ()
- ✅ support N:M match
- ✅ complete modify
- ✅ support then (transaction in/at not have/has not minutesclass)

### Q4: limitation
> **Question**: confirmation is no need need to validate? 

**✅ Your Answer**: C - allowconfirmationhighminutes (≥ 80), lowminutes need confirmation

**Decision**: minutesstrategy
- **highminutesfast** (score ≥ 80):
 - supportconfirmation have/has highminutes
 - can daterange, amountrange
 - UI To Be Confirmedandamount
- **lowminutesconfirmation** (60 ≤ score < 80):
 - Required, not support
 - Frontendtableallowconfirmation/reject
 - use to each 
- **confirmation for **:
 - :confirmation, amount, daterange
 - sample ( 5 )
 - use Required " already review" just/only can confirmation
- ****:
 - each, time, confirmation
 - supportundo ( in/at 24 hours can undoconfirmation)

### Q5: pattern
> **Question**: is no use match as/for ? 

**✅ Your Answer**: B + embedding - then , use embedding match

**Decision**: Embedding can match (high)

**implementationsolution**:
- **Embedding ** (usemodel, such as sentence-transformers):
 - for each BankStatementTransaction generate embedding
 - for each JournalEntry memo generate embedding
 - calculate , as/for ""minutes 
 
- **pattern** ( then):
 - `MerchantPattern` table:
 ```
 merchant_name, canonical_merchant,
 preferred_account_id, confidence,
 last_matched_at, match_count
 ```
 - each use confirmationmatch, updatepattern:
 ```
 IF MERCHANT :
 UPDATE match_count, confidence
 ELSE:
 INSERT pattern
 ```
 - to transaction, excessively lowminutes, priorityrecommendationaccount
 
- **timepattern** (subscribeclass):
 - Duration (such as eachmonthdays, amount)
 - give minutes (such as +10 minutes)
 - sample:eachmonth 25 500 SGD 
 
- **Integration**:
 ```
 score = 40% amount_match 
 + 25% date_match 
 + 20% embedding_similarity // NEW
 + 10% business_logic 
 + 5% pattern_bonus // pattern + timepattern
 ```

**table**:
```sql
-- pattern
CREATE TABLE merchant_patterns (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL,
 merchant_name VARCHAR(255),
 canonical_merchant VARCHAR(255),
 preferred_account_id UUID,
 confidence DECIMAL(3,2), -- 0-1
 match_count INT,
 last_matched_at TIMESTAMP
);

-- Embedding cache
CREATE TABLE transaction_embeddings (
 id UUID PRIMARY KEY,
 source_type ENUM ('bank_txn', 'journal_entry'),
 source_id UUID,
 embedding VECTOR(384), -- pgvector extension
 created_at TIMESTAMP
);
```

**good**:
- ✅ , no/none need complex ML 
- ✅ mostpatternQuestion (, class)
- ✅ can optimization ( use embedding, can )
- ✅ support (embedding model)
- ✅ can good (calculate)

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + Basic matching algorithm | 16h |
| Week 2 | Scoring dimensions + Special scenarios | 20h |
| Week 3 | Review queue + Anomaly detection | 16h |
| Week 4 | Frontend UI + Tuning testing | 20h |
| Week 5 | Embedding integration + Time-aware rules + Dual-layer model | 16h |

**Total estimate**: 88 hours (5 weeks)
