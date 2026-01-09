# 📋 EPIC Q&A Decision Summary

> **Completion Date**: 2026-01-09  
> **Branch**: `feat/epic-planning`  
> **Status**: ✅ All 24 questions answered and documented

---

## ✅ Completion Status

| Metric | Value |
|--------|-------|
| Total Questions | 24 |
| Answered | 24 (100%) |
| Documented | ✅ EPIC-002 ~ EPIC-006 |
| Committed to Branch | ✅ feat/epic-planning |

---

## 🎯 Key Decisions Summary

### EPIC-002: Double-Entry Bookkeeping Core (Q1-Q4)

| # | Question | Decision |
|---|----------|----------|
| Q1 | Account Coding Standard | **US GAAP Taxonomy** - International financial standard |
| Q2 | Multi-Currency Support | **Full Support** - User-configurable base currency |
| Q3 | Draft Entry Balance | **Excluded** - Only posted/reconciled entries count |
| Q4 | Entry Voiding Method | **Reversal Vouchers** - Red entries preserve audit trail |

### EPIC-003: Smart Statement Parsing (Q5-Q9)

| # | Question | Decision |
|---|----------|----------|
| Q5 | Bank Priority | **Universal Structure + Extension Fields** - DBS/CITIC/Maybank/Wise/Brokerages/Insurance |
| Q6 | Cost Control | **OpenRouter Layer** - $2/day quota management |
| Q7 | Failure Handling | **Layered Retry** - Gemini 3 Flash → Stronger Models → Manual Edit |
| Q8 | Account Linking | **AI Suggestion + User Confirmation** - Parse → Match Recommendation → User Confirm |
| Q9 | Historical Import | **Async ETL Task Queue** - Each upload corresponds to independent task |

### EPIC-004: Reconciliation Engine & Matching (Q10-Q14)

| # | Question | Decision |
|---|----------|----------|
| Q10 | Threshold Adjustability | **Fixed** (85/60) - Optimize after collecting real data |
| Q11 | Unmatched Transaction Handling | **AI Template Suggestion + Time-Aware Rules** - Rules can be effective by period |
| Q12 | Duplicate Matching | **Dual-Layer Model** - Account Event (immutable) + Ontology Event (versioned) |
| Q13 | Batch Operation Safety | **Layered Batch** - ≥80 score batch allowed, <80 individual confirmation |
| Q14 | Historical Learning | **Embedding Vectors + Merchant/Time Patterns** - Simple and efficient pattern recognition |

### EPIC-005: Financial Reports & Visualization (Q15-Q19)

| # | Question | Decision |
|---|----------|----------|
| Q15 | Report Period Definition | **Natural Month** (1-31) - Most intuitive cycle |
| Q16 | Exchange Rate Source | **Yahoo Finance API** - Free and accurate |
| Q17 | Historical Exchange Rate | **Transaction Date Rate** - GAAP compliant |
| Q18 | Chart Library | **ECharts** - Supports candlestick and financial charts |
| Q19 | Export Format | **CSV (data export) + PDF (formatted reports)** - Layered output |

### EPIC-006: AI Financial Advisor (Q20-Q24)

| # | Question | Decision |
|---|----------|----------|
| Q20 | API Availability | **Error Message** - No fallback, wait for recovery |
| Q21 | Chat History | **Permanent Retention** - User can manually delete |
| Q22 | Disclaimer | **First-Use Modal** - Single consent + persistent reminder |
| Q23 | Call Limit | **Unlimited** - OpenRouter handles $2/day quota |
| Q24 | Proactive Alerts | **Passive Only** - User-initiated questions, no push notifications |

---

## 🔄 Design Highlights

### 1️⃣ Architectural Innovations

#### **Dual-Layer Event Model** (EPIC-004 Q12)
```
BankStatementTransaction (Account Event - Immutable Raw Layer)
  ↓ (Versioned Mapping)
ReconciliationMatch v1, v2, v3, ... (Ontology Event - Mutable Analysis Layer)
  ↓ (Currently Active)
JournalEntry

Benefits:
- Complete audit trail (raw data never lost)
- Flexible N:M mapping (1:N, N:1, N:M)
- Rule evolution (same transaction can have different classifications in different periods)
```

#### **Time-Aware Rule Engine** (EPIC-004 Q11)
```
ReconciliationRule:
  - name: "Salary Recognition Rule (Jan-Mar only)"
  - conditions: {amount_range: [4000, 6000]}
  - effective_from: 2025-01-01
  - effective_to: 2025-03-31
  - actions: {account_debit: "Bank", account_credit: "Income Salary"}

Usage: Load effective rules during reconciliation to enhance AI suggestion accuracy
```

#### **Async ETL Task Queue** (EPIC-003 Q9)
```
StatementProcessingTask:
  - Create task record on upload
  - Independent async processing (supports retry, priority, progress tracking)
  - Supports multi-file parallel processing
  - User can view processing status in real-time

Advantages: Efficient batch import, good user experience
```

### 2️⃣ AI Integration Intelligence

#### **Layered Retry Strategy** (EPIC-003 Q7)
```
Upload PDF
  ↓
Try Gemini 3 Flash (fast, cheap)
  ├─ ✅ Success → Return results
  └─ ❌ Fail → Prompt user to retry
      ↓
      Try Gemini 2.0 / GPT-4 (stronger models)
      ├─ ✅ Success → Return results
      └─ ❌ Fail → Show partial results + edit form
```

#### **Embedding Vector Matching** (EPIC-004 Q14)
```
Merchant Pattern Recognition:
  MerchantPattern: {
    merchant_name: "Starbucks",
    preferred_account: "Living Expenses",
    confidence: 0.95,
    match_count: 23
  }

Time Pattern Recognition:
  - 25th of each month $500 → Rent
  - Every Friday $100 → Food delivery

Match Scoring:
  score = 40% amount + 25% date + 20% embedding + 10% logic + 5% pattern
```

#### **Universal Structure + Extension Fields** (EPIC-003 Q5)
```
BankStatementTransaction:
  - Core fields: txn_date, amount, direction, description
  - Extension fields (JSONB):
    - bank_specific_data: {transaction code, reference, terminal, etc.}
    - institution_type: bank/brokerage/insurance/wallet
    - custom_fields: User-defined fields

Prompt Templates:
  templates/dbs.yaml
  templates/citic.yaml
  templates/brokerage_generic.yaml
  templates/insurance_generic.yaml
```

### 3️⃣ Financial Compliance

- **US GAAP Coding** → International financial standard
- **Reversal Vouchers** → Audit log integrity
- **Transaction Date FX Rate** → GAAP accounting principle (not report date rate)
- **Embedding Vector Cache** → Historical classification traceable

### 4️⃣ User Experience Design

#### **Security First**
- Batch operation limits: ≥80 score supports batch, <80 requires individual confirmation
- Batch confirmation modal shows total count, total amount, examples
- Can undo batch operations within 24 hours

#### **Progressive Interaction**
- Parse → AI Suggestion → User Confirmation (not forced)
- Account linking: AI recommends → User confirms (not automatic)
- Unmatched transactions: AI suggests template → User accepts/modifies

#### **Passive AI**
- Only answers when user actively asks questions
- No push notifications, alerts, or proactive reminders
- User has complete control over interaction timing

---

## 📊 Project Timeline Re-estimation

Adjusted based on decision complexity:

| EPIC | Original | New | Δ | Reason |
|------|----------|-----|---|--------|
| EPIC-001 | 2w | 2w | → | Infrastructure unchanged |
| EPIC-002 | 3w | 3w | → | GAAP/Multi-currency/Reversal within expectations |
| EPIC-003 | 3w | **4w** | +1w | Universal structure + ETL queue + multi-model retry |
| EPIC-004 | 4w | **5w** | +1w | Dual-layer model + embedding + rule engine |
| EPIC-005 | 3w | 3w | → | ECharts + PDF not too complex |
| EPIC-006 | 2w | 2w | → | Passive AI simplifies implementation |
| **Total** | **15-18w** | **17-20w** | **+2w** | Architecture upgrade worth the investment |

---

## 🚀 Next Steps

### Phase 1: Validation & Review (Week 1)
- [ ] Technical review of decision proposals (Architect role)
- [ ] Requirements confirmation (PM role)
- [ ] Cost assessment (whether 1-2 week addition acceptable)

### Phase 2: Prototype Development (Week 2-3)
- [ ] EPIC-002 core development (highest priority)
- [ ] EPIC-001 improvements (pre-commit hooks, CI/CD)

### Phase 3: Data Accumulation (Week 4-12)
- [ ] EPIC-003 statement parsing
- [ ] EPIC-004 reconciliation engine (critical algorithm tuning requires data)
- [ ] Accumulate real reconciliation data

### Phase 4: Reports & AI (Week 13-18)
- [ ] EPIC-005 financial reports
- [ ] EPIC-006 AI financial advisor
- [ ] Adjust based on data feedback

### Phase 5: Feedback Iteration (v1.5+)
- [ ] Parameter tuning (thresholds, weights)
- [ ] New feature expansion (cash flow statement, budget management)
- [ ] Performance optimization (cache, materialized views)

---

## 📑 Related Documents

- [EPIC-002.double-entry-core.md](./EPIC-002.double-entry-core.md)
- [EPIC-003.statement-parsing.md](./EPIC-003.statement-parsing.md)
- [EPIC-004.reconciliation-engine.md](./EPIC-004.reconciliation-engine.md)
- [EPIC-005.reporting-visualization.md](./EPIC-005.reporting-visualization.md)
- [EPIC-006.ai-advisor.md](./EPIC-006.ai-advisor.md)

---

**Recorder**: Zitian Wang  
**Completion Time**: 2026-01-09 20:04 UTC  
**Git Commit**: `9ceeb62`
