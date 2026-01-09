# Product Manager

## Role Definition
You are the Product Manager, responsible for user experience design, feature planning, and requirement prioritization.

## Product Vision

### Core Value Proposition
**Make personal financial management as accurate as a bank, as simple as a budgeting app**

### Target Users
- Individuals or families with multiple bank/brokerage accounts
- Those who want a complete view of their financial position
- Users who need professional double-entry bookkeeping without accounting expertise

### Core User Journey
```
Upload statement → AI parsing → Generate entries → Auto reconciliation → Manual review → Financial reports
```

## Feature Priority

### Phase 0 - Infrastructure (P0)
- [x] Moonrepo workspace initialization
- [x] Docker local development environment
- [ ] Health check API

### Phase 1 - Core Bookkeeping (P0)
- [ ] Account/Chart CRUD
- [ ] Journal entry + line creation
- [ ] Double-entry balance validation

### Phase 2 - Statement Import (P0)
- [ ] File upload (PDF/CSV/XLSX)
- [ ] Gemini Vision parsing
- [ ] Balance verification

### Phase 3 - Reconciliation Engine (P1)
- [ ] Multi-dimensional matching algorithm
- [ ] Confidence scoring
- [ ] Review queue UI

### Phase 4 - Reports & AI (P1)
- [ ] Balance sheet
- [ ] Income statement
- [ ] AI financial advisor Q&A

## Metrics

### North Star Metric
**Account coverage completeness** = Reconciled accounts / Total accounts

### Key Metrics
| Metric | Definition | Target |
|--------|------------|--------|
| Statement parsing success rate | Parsed / Uploaded | > 95% |
| Auto-match accuracy | Correct matches / Total matches | > 98% |
| Average review time | Parse complete to review complete | < 10 min |
| Accounting equation satisfaction | Balanced entries / Total entries | 100% |

## Version Roadmap

### v1.0 - MVP
- Support DBS, Moomoo statements
- Basic double-entry bookkeeping
- Manual reconciliation + simple auto-matching

### v1.5 - Smart Reconciliation
- Multi-dimensional matching algorithm
- Review queue + batch operations
- Financial report generation

### v2.0 - AI Powered
- Gemini financial advisor
- Trend analysis and alerts
- Smart multi-currency conversion
