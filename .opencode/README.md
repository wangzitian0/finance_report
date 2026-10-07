# OpenCode Configuration

OpenCode/Oh-My-OpenCode configuration for `finance_report`. The authoritative
behavioral entry point is [`AGENTS.md`](../AGENTS.md); the multi-runtime bridge
(symlinks, MCP baseline, per-runtime agents) is documented in
[`.claude/README.md`](../.claude/README.md).

## Layout

```
.opencode/
├── oh-my-openagent.json   # OpenCode agent/model routing + enabled skills
└── README.md              # This file
```

## Skills

The project skill library lives in the top-level `skills/` directory,
managed via `dev_env` SSOT and published through `ws_publish.py`.
Multi-runtime mirrors (`.claude/skills/`, `.codex/skills/`, `.agents/skills/`)
symlink directly into `skills/` (guard: `tests/tooling/test_agent_runtime_symlinks.py`).

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
