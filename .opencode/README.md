# OpenCode Configuration

This directory contains the OpenCode/Oh-My-OpenCode configuration for the `finance_report` project.

## Directory Structure

```
.opencode/
├── oh-my-opencode.json    # Agent configurations (models, skills, prompts)
├── skills/                # Skills organized by category
│   ├── domain/            # Project-specific (from SSOT)
│   │   ├── accounting/    # Double-entry bookkeeping
│   │   ├── reconciliation/# Statement matching
│   │   ├── reporting/     # Financial statements
│   │   ├── extraction/    # Document parsing
│   │   ├── schema/        # Database models
│   │   ├── development/   # Moon commands, CI/CD
│   │   ├── infra-operations/  # Infrastructure operations & deployment
│   │   └── secrets-management/  # Environment variables, Vault, multi-env
│   │
│   ├── professional/      # Reusable expertise
│   │   ├── backend-development/  # FastAPI, security (11 refs)
│   │   ├── frontend-react/       # Next.js + Vercel (44 rules)
│   │   ├── qa-testing/           # Testing strategies
│   │   ├── ui-ux-design/         # UI/UX design
│   │   ├── product-management/   # PRD, RICE
│   │   └── auditor/              # Financial auditing
│   │
│   └── meta/              # About skills themselves
│       └── skill-writer/  # Creating new skills
│
├── package.json           # Oh-My-OpenCode plugin dependencies
└── README.md              # This file
```

---

## Design Philosophy: Why This Architecture?

### Core Principle: Leverage AI's Unique Advantages

**AI systems should NOT blindly mimic human organizations.** This architecture is optimized for AI's unique capabilities:

| Human Organization | AI System (This Project) |
|-------------------|-------------------------|
| **Multiple independent brains** | **Single LLM with perfect context** |
| Parallel teams (Backend/Frontend/QA) | Single orchestrator (Sisyphus) |
| Communication via docs/meetings | Direct memory sharing |
| Interface contracts (OpenAPI) needed | Context continuity eliminates contracts |
| Integration testing catches bugs | Code naturally consistent |
| Fixed employment cost → parallel to avoid waste | Pay-per-use → serial is cheaper |

### Why Not More Sub-Agents?

**Question**: Why not have separate `backend-developer`, `qa-engineer`, `product-manager` agents like human companies?

**Answer**: Because AI doesn't have human limitations:

```
Human Company Pattern (NOT for AI):
├── PM writes PRD
├── Architect designs API contract (OpenAPI)
├── Backend team implements API (parallel)
├── Frontend team builds UI with mocks (parallel)
├── QA team writes tests (parallel)
└── Integration phase: Fix mismatches (联调)

Problem: Different teams interpret same spec differently → integration bugs

AI Optimal Pattern (This Project):
├── Sisyphus loads skills (domain/accounting, professional/backend-dev, etc.)
├── Designs API schema (in memory)
├── Implements backend (using exact schema from step 2)
├── Implements frontend (with perfect knowledge of backend from step 3)
└── Writes tests (testing actual implementation, not assumptions)

Advantage: Same "brain" → no interpretation gaps → no integration phase needed
```

### Cost-Benefit Analysis: Parallel vs. Serial

**Parallel Pattern (like human companies)**:
```typescript
// Hypothetical parallel approach
const [backend, frontend, tests] = await Promise.all([
  background_task({agent: "backend-dev", prompt: "Implement API per spec"}),
  background_task({agent: "frontend-dev", prompt: "Build UI per spec"}),
  background_task({agent: "qa-engineer", prompt: "Write tests per spec"})
])
// Then: Integration phase to fix mismatches (2-3 additional API calls)

Cost: 3-6 API calls
Time: ~2 minutes
Risk: Integration bugs from spec interpretation differences
```

**Serial Pattern (this project)**:
```typescript
// Current approach
const result = await task({
  agent: "sisyphus",
  prompt: "Implement reconciliation feature",
  skills: ["domain/reconciliation", "professional/backend-development", "professional/qa-testing"]
})
// Sisyphus maintains context across backend → frontend → tests

Cost: 1 API call
Time: ~3 minutes  
Risk: Zero (same reasoning engine = natural consistency)
```

**ROI**: Spending 5x cost to save 1 minute → **Not worth it**

### When DOES Parallelization Make Sense?

**Only when ALL conditions are met**:

1. ✅ **Tasks are truly independent** (no shared context needed)
2. ✅ **No integration required** (outputs can be used independently)
3. ✅ **IO-intensive** (waiting for external responses)
4. ✅ **Time savings worth cost** (significant speedup justifies extra API calls)

**In this project, parallel execution is ONLY used for**:

| Scenario | Why Parallel Works |
|----------|-------------------|
| **Code exploration** (`explore` agents) | Independent file searches, results merge-able |
| **External docs** (`librarian` agents) | Fetching different API docs, no shared context |
| **Multi-module review** (future) | Reviewing different files, outputs are suggestion lists |

**NOT used for**:
- ❌ Backend + Frontend development (needs shared API contract)
- ❌ Implementation + Testing (tests depend on implementation details)
- ❌ PRD + Code (code depends on requirements)

---

## Architecture Overview

```
User Request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Sisyphus (Orchestrator)                                     │
│  Model: copilot/claude-sonnet-4.5 (Claude Sonnet 4.5)        │
│  Skills: domain/development, domain/schema, domain/accounting│
│          domain/reconciliation, professional/backend-dev,    │
│          meta/skill-writer                                   │
│  Role: Handle most tasks directly; delegate only when needed │
│                                                              │
│  Workflow:                                                   │
│  1. Load relevant skills (instant, zero cost)                │
│  2. Execute tasks serially (maintain context continuity)     │
│  3. Delegate only for:                                       │
│     - Parallel exploration (explore/librarian)               │
│     - Visual work (frontend-ui-ux-engineer)                  │
│     - Deep architecture (oracle)                             │
└─────────────────────────────────────────────────────────────┘
    │ Delegates to (only when necessary)
    ├── explore            (FREE - parallel codebase grep)
    ├── librarian          (FREE - external docs/OSS grep)
    ├── frontend-ui-ux-engineer (visual/styling - MANDATORY)
    ├── multimodal-looker  (image/PDF analysis)
    └── oracle             (architecture decisions - EXPENSIVE)
```

---

## Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-------------|
| **Sisyphus** | Claude Opus Thinking | Orchestrator with full domain knowledge | **Default for all tasks** (Backend, QA, PM, Documentation) |
| `explore` | Gemini 3 Flash | Fast codebase exploration | Parallel code searches (background) |
| `librarian` | Gemini 3 Flash | External documentation | Parallel API doc lookups (background) |
| `frontend-ui-ux-engineer` | Gemini 3 Pro High | Visual/UI design | **Mandatory** for styling, colors, layouts |
| `multimodal-looker` | Gemini 3 Pro High | Image/PDF analysis | Diagram/document analysis |
| `oracle` | Claude Opus Thinking | Deep architecture | Complex design decisions (use sparingly) |

### Why Skills Instead of Agents?

| Capability | Implementation | Reasoning |
|-----------|---------------|-----------|
| **Backend Development** | ✅ Skill (loaded by Sisyphus) | Logical reasoning task → main model sufficient |
| **QA Testing** | ✅ Skill (loaded by Sisyphus) | Test strategies are documented knowledge |
| **Product Management** | ✅ Skill (loaded by Sisyphus) | PRD templates + RICE algorithm |
| **Auditing** | ✅ Skill (loaded by Sisyphus) | Accounting rules are deterministic logic |
| **UI/UX Design** | ❌ Agent (frontend-ui-ux-engineer) | **Visual aesthetics need specialized model** |
| **Architecture** | ❌ Agent (oracle) | **Deep reasoning needs special configuration** |

**Key Insight**: 
- **Skill** = Knowledge base (can be learned instantly by LLM)
- **Agent** = Specialized capability (requires different model or training)

Most "roles" in human companies are just **knowledge domains**, not fundamentally different capabilities. A sufficiently powerful LLM (Claude Opus) can handle all of them by loading appropriate skills.

---

## Skills by Category

### Domain Skills (Project-Specific)

Generated from `docs/ssot/` - the Single Source of Truth for this project.

| Skill | Path | Source |
|-------|------|--------|
| Accounting | `domain/accounting` | [docs/ssot/accounting.md](../docs/ssot/accounting.md) |
| Reconciliation | `domain/reconciliation` | [docs/ssot/reconciliation.md](../docs/ssot/reconciliation.md) |
| Reporting | `domain/reporting` | [docs/ssot/reporting.md](../docs/ssot/reporting.md) |
| Extraction | `domain/extraction` | [docs/ssot/extraction.md](../docs/ssot/extraction.md) |
| Schema | `domain/schema` | [docs/ssot/schema.md](../docs/ssot/schema.md) |
| Development | `domain/development` | [docs/ssot/development.md](../docs/ssot/development.md) |
| Infra Operations | `domain/infra-operations` | Infrastructure deployment, operations, debugging, and monitoring |
| **Secrets Management** | `domain/secrets-management` | Environment variables, Vault integration, multi-environment strategy |

### Professional Skills (Reusable)

Curated best practices and patterns applicable across projects.

| Skill | Path | Contents |
|-------|------|----------|
| Backend Development | `professional/backend-development` | SKILL.md + 11 reference docs (API design, security, testing, devops, etc.) |
| Frontend React | `professional/frontend-react` | SKILL.md + 44 Vercel optimization rules |
| QA Testing | `professional/qa-testing` | SKILL.md + 3 references + automation scripts |
| UI/UX Design | `professional/ui-ux-design` | SKILL.md + 12 CSV datasets + analysis scripts |
| Product Management | `professional/product-management` | SKILL.md + PRD templates + RICE prioritizer |
| Auditor | `professional/auditor` | SKILL.md (accounting rules, reconciliation logic) |

### Meta Skills

| Skill | Path | Purpose |
|-------|------|---------|
| Skill Writer | `meta/skill-writer` | Creating new skills (used by Sisyphus for documentation) |

---

## Usage

### Skills (Auto-loaded)

Skills are automatically loaded by agents based on `oh-my-opencode.json` configuration:

```jsonc
{
  "agents": {
    "Sisyphus": {
      "skills": [
        "domain/development",      // Loaded automatically
        "domain/schema",
        "domain/accounting",
        "professional/backend-development",
        "meta/skill-writer"
      ]
    }
  }
}
```

### On-Demand Skill Loading

```bash
# Manually load additional skills during conversation
/skill domain/reconciliation
/skill professional/frontend-react
```

### Agent Delegation

Agents are invoked by Sisyphus only when necessary:

```typescript
// Exploration (parallel, background)
background_task(agent="explore", prompt="Find all authentication patterns")
background_task(agent="librarian", prompt="Fetch FastAPI best practices")

// Visual work (mandatory delegation)
task(agent="frontend-ui-ux-engineer", prompt="Design reconciliation dashboard")

// Architecture decisions (expensive, use sparingly)
task(agent="oracle", prompt="Evaluate microservices vs monolith for this scale")
```

---

## Performance Comparison

### Typical Feature Development

**Serial (Current Architecture)**:
```
Sisyphus workflow:
├── Design API schema (30s)
├── Implement backend (60s)   ← uses schema from memory
├── Implement frontend (60s)  ← knows exact backend API
└── Write tests (30s)         ← tests actual implementation

Total: ~3 minutes, 1 API call, zero integration bugs
```

**Parallel (Human-Company Style)**:
```
Hypothetical parallel workflow:
├── Architect designs schema (30s)
├── Parallel execution (60s):
│   ├── Backend implements API (might misinterpret schema)
│   ├── Frontend builds UI (might assume wrong fields)
│   └── QA writes tests (might test wrong behavior)
└── Integration phase (60s):
    ├── Fix backend/frontend mismatch
    ├── Update tests
    └── Re-verify

Total: ~2 minutes, 5-6 API calls, integration bugs likely
```

**Verdict**: Serial is cheaper, more reliable, only 1 minute slower.

---

## When to Add More Agents?

### Decision Criteria

Add a new agent ONLY when:

1. ✅ **Main model cannot do it** (e.g., visual aesthetics, image analysis)
2. ✅ **Tasks are truly independent** (e.g., parallel code searches)
3. ✅ **Time savings justify cost** (e.g., review phase can be parallelized)
4. ✅ **No integration complexity** (e.g., review outputs are just suggestions)

### Future Candidates

| Potential Agent | Justification | Priority |
|----------------|---------------|----------|
| `code-reviewer-backend` | Parallel review of different modules | Medium |
| `code-reviewer-frontend` | Parallel review of different modules | Medium |
| `code-reviewer-qa` | Parallel review of test quality | Low |

**Note**: These would ONLY be used AFTER code is written, during review phase.

---

## Related Documentation

- [AGENTS.md](../AGENTS.md) - Complete behavioral guidelines and agent roles
- [docs/ssot/](../docs/ssot/) - Single Source of Truth for domain rules
- [target.md](../target.md) - Project goals and decision criteria

---

## Key Takeaways

1. **AI ≠ Human Company**: Don't blindly copy human organizational patterns
2. **Skills > Agents**: Most "roles" are just knowledge domains, not specialized capabilities
3. **Context Continuity > Speed**: Serial execution with perfect context beats parallel with integration bugs
4. **Parallel Only When Independent**: Use parallelization strategically (exploration, review)
5. **Cost-Conscious**: 1 API call (serial) vs 5 API calls (parallel) - choose wisely
