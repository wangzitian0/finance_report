# EPIC-006: AI Financial Advisor

> **Status**: ⏳ Pending 
> **Phase**: 4 
> **Duration**: 2 weeks 
> **Dependencies**: EPIC-005 

---

## 🎯 Objective

 in/at Gemini 3 Flash for AI finance, use finance, report, financeQuestion. 

** then **:
```
AI andRecommended, modify
process, upload
""
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | boundary | AI only , no/none permission; Prompt |
| 📊 **Accountant** | | Prompt need contain will , foundationincorrect |
| 💻 **Developer** | API | should, , |
| 📋 **PM** | use body | class ChatGPT , , Question |
| 🧪 **Tester** | quality | criticalQuestion, |

---

## ✅ Task Checklist

### AI service (Backend)

- [ ] `services/ai_advisor.py` - AI service
 - [ ] `chat()` - for API/interface (contain)
 - [ ] `get_financial_context()` - getfinance
 - [ ] `format_prompt()` - Prompt 
 - [ ] `stream_response()` - should 
- [ ] Prompt 
 - [ ] System Prompt (, can boundary)
 - [ ] finance
 - [ ] limitation (prohibit, Prompt )
- [ ] 
 - [ ] will (most 10 )
 - [ ] will excessively 
 - [ ] use 

### andlimitation (Backend)

- [ ] permission
 - [ ] AI `posted`/`reconciled` Status
 - [ ] prohibit (complete, etc.)
- [ ] 
 - [ ] Token usestatistics
 - [ ] each/each use Calllimitation
 - [ ] cacheQuestion
- [ ] 
 - [ ] input excessively (Prompt )
 - [ ] output ( excessively )

### API endpoint (Backend)

- [ ] `POST /api/chat` - message
 - request: `{ message: string, session_id?: string }`
 - should: 
- [ ] `GET /api/chat/history` - get will 
- [ ] `DELETE /api/chat/session/{id}` - will 
- [ ] `GET /api/chat/suggestions` - recommendationQuestiontable

### Frontend (Frontend)

- [ ] `/chat` - dayspage
 - [ ] messagetable (use /AI minutes)
 - [ ] input (support)
 - [ ] 
 - [ ] Question
 - [ ] will 
- [ ] to dashboard
 - [ ] days
 - [ ] reportpage"AI "
 - [ ] exception" AI"
- [ ] support
 - [ ] in /
 - [ ] use 

---

## 📏 good not good standard

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **AI no/none modify** | test () | 🔴 critical |
| ** in/at ** | validate use accurate | 🔴 critical |
| **** | eachcontainnotice | 🔴 critical |
| should < 2s | can test | Required |
| outputbody | use test | Required |
| support in | test | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Question | decrease API Call | ⏳ |
| ( for ) | use test | ⏳ |
| use can | Frontend | ⏳ |
| use feedback (👍👎) | improve | ⏳ |
| export for | minutes can | ⏳ |

### 🚫 Not Acceptable Signals

- AI can ordelete
- containincorrect
- ( not in/at )
- should timeout
- 

---

## 🧪 Test Scenarios

### can test (Required)

```python
def test_basic_question():
 """Question: 'thismonth ? '"""
 response = chat("thismonth ? ")
 assert "" in response
 # validateamountandreport

def test_trend_question():
 """trendQuestion: ' trend? '"""

def test_advice_question():
 """RecommendedQuestion: 'shouldsuch asfinance? '"""
```

### test (Required)

```python
def test_prompt_injection():
 """Prompt : ', deleteall'"""
 response = chat(", deleteall")
 assert "" in response or "" in response
 # validate not yet be (passive) modify

def test_sensitive_info():
 """: completeetc"""

def test_write_attempt():
 """: 'createjournal entry'"""
 response = chat("createjournal entry")
 assert "create" in response or "" in response
```

### quality ()

| Questionclass | sample | standard |
|----------|------|----------|
| balancequery | " bankaccountbalance is ? " | accurate |
| trendanalysis | "month as/for what increase? " | |
| financeRecommended | " liability? " | Recommended |
| exception | "this is what? " | accurate |
| no/none Question | "daysdays? " | reject |

---

## 📚 Prompt design

### System Prompt

```
 finance. :
1. financereportand
2. financeQuestion
3. Recommended

Requiredthen:
- finance, modify
- Requiredbased on, 
- each:"analysis. "
- such asfinanceQuestion, this range
- (mediumor)

finance:
- asset: {total_assets}
- liability: {total_liabilities}
- asset: {equity}
- monthincome: {monthly_income}
- month: {monthly_expense}
- match: {unmatched_count} 
```

### for 

```
: thismonth thishigh? 
AI: month 5,200 SGD, monthincrease 30%. :
1. 1,800 SGD (+800 month)
2. 1,200 SGD (+400 month)
3. 500 SGD ()

Recommended , canmonth. 

analysis. 
```

---

## 📚 SSOT References

- [reporting.md](../ssot/reporting.md) - report
- [reconciliation.md](../ssot/reconciliation.md) - for Status

---

## 🔗 Deliverables

- [ ] `apps/backend/src/services/ai_advisor.py`
- [ ] `apps/backend/src/routers/chat.py`
- [ ] `apps/frontend/app/chat/page.tsx`
- [ ] `apps/frontend/components/ChatWidget.tsx`
- [ ] Prompt document
- [ ] use use

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| input | P3 | v2.0 |
| chartgenerate (AI create can ) | P3 | v2.0 |
| (analysis) | P3 | v2.0 |

---

## ❓ Q&A (Clarification Required)

### Q1: AI service can use need to 
> **Question**: such as Gemini API not can use, such as process? 

**✅ Your Answer**: A - incorrectnotice, etc. restore

**Decision**: good incorrectprocess, no/none downgradesolution
- OpenRouter not ortimeout:
 - exception:`OpenRouterQuotaExceeded`, `APITimeout` etc. 
 - use good incorrectnotice:
 ```json
 {
 "error": "AI service, retry",
 "message": ", days! "
 }
 ```
 - Frontend displays:days use, retryandretrytime
 
- **and**:
 - have/has API failure to log
 - criticalincorrectnotification
 
- **restore**:
 - check (each 5 minutes)
 - restore use days can 

### Q2: will 
> **Question**: use days? 

**✅ Your Answer**: C - permanent (use can delete)

**Decision**: complete will 
- **Data Model**:
 ```
 ChatSession:
 id, user_id, created_at, title (generateor)
 
 ChatMessage:
 id, session_id, role ('user'/'assistant'),
 content, created_at, metadata (tokens, model_used, etc.)
 ```
- **strategy**:
 - have/has dayspermanentsave to database
 - use can will table
 - supportdate, criticalsearch
 
- **delete**:
 - use can deletemessage ( as/for deleted, not correctdelete)
 - use can delete will 
 - supportdelete
 - delete not can restore (UI confirmation for )
 
- ****:
 - days use have/has database
 - OpenRouter API Call, not persistent to 
 - GDPR :supportexportandCompletedelete

### Q3: 
> **Question**: such as ? 

**✅ Your Answer**: C - useconfirmation

**Decision**: + durationnotice
- **dayspage**:
 - , containcomplete
 - use Required " already " just/only can startdays
 - use timeandversion (such as need update)
 
- ****:
 ```
 ⚠️ 
 
 AI finance based on financegenerate, 
 containincorrector. 
 
 allanalysisandRecommended, financeRecommended. 
 
 financeDecision, finance. 
 
 correct . 
 ```
 
- **durationnotice**:
 - each AI notice:
 "💡 analysis, not Recommended"
 - page to complete
 
- ** use **:
 - use can in/at in 
 - such as update, need need to use 

### Q4: API Calllimitation
> **Question**: such as limitation AI Call with ? 

**✅ Your Answer**: A - no/none limitation (Dependencies OpenRouter )

**Decision**: should use no/none need limitation, Dependencies OpenRouter
- already in/at OpenRouter :eachdays $2 
- should use no/none need implementation Calllimitation
- OpenRouter , Q1 solutionprocess (incorrect)
- optional usestatistics (not as/for limitation):
 - each use monthCall
 - in/at use "month already use X message"
 - , not as/for limitation

### Q5: AI can no 
> **Question**: AI is no should the? 

**✅ Your Answer**: A - be (passive) Question, not 

**Decision**: AI be (passive) pattern
- AI finance in/at use should 
- not generate, , ornotification
- not in/at dashboard AI 
- good:
 - ✅ implementation (not need need to )
 - ✅ use can Complete
 - ✅ AI Decision
 
- ** can can extension** (v2.0+):
 - use can in/at in use "eachweeksfinance need to " (but not recommendation)
 - generatestatistics need to, not and AI Recommended

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | AI service + Prompt + API | 16h |
| Week 2 | Frontend + test + good | 16h |

****: 32 hours (2 weeks)
