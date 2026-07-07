# OpenCode Configuration

OpenCode/Oh-My-OpenCode configuration for `finance_report`. The authoritative
behavioral entry point is [`AGENTS.md`](../AGENTS.md); the multi-runtime bridge
(symlinks, MCP baseline, per-runtime agents) is documented in
[`.claude/README.md`](../.claude/README.md).

## Layout

```
.opencode/
├── oh-my-openagent.json   # OpenCode agent/model routing + enabled skills
├── skills/                # Canonical skill library (other runtimes symlink in)
│   └── domain/            # Project-specific operational knowledge only
└── README.md              # This file
```

## Skills

Only **project-specific** skills live here (accounting, reconciliation,
reporting, extraction, schema, development, preflight, ac-workflow,
github-operations, secrets-management, infra-operations). Generic-expertise
packs (backend/frontend/QA/PM/UI) were removed in #1657: frontier models carry
that knowledge natively, and version-specific questions route to live docs
(context7 MCP) rather than frozen snapshots. Before adding a skill, ask: does
this contain facts *about this repo* that the model cannot read from SSOT/code
directly? If not, don't add it.

Add or rename skills **here only** — `.claude/skills/` and `.codex/skills/` are
flat symlinks (guard: `tests/tooling/test_agent_runtime_symlinks.py`).

## Agents & models

`oh-my-openagent.json` routes OpenCode's named agents; entries like
`agents-rules` / `tools-index` are oh-my-opencode plugin built-ins, not repo
skills. Model pins are **per-runtime mechanics owned by whoever runs that
runtime** — they lag frontier releases by design and are tuned here, never in
the shared `AGENTS.md`. Claude Code's equivalents live in `.claude/agents/`.

Delegation judgment (when to fan out vs. work in the main loop) is culture, not
config: see `vision.md` Good Taste 6 — parallelism is bounded by write
conflicts, not compute cost; the scarce resource is the user's review
bandwidth.
