# Claude Code bridge

This directory makes the repo open-and-develop for **Claude Code**, alongside
**Codex**, **Antigravity**, and **OpenCode**. The single source of truth lives
elsewhere; everything here is a symlink so there is nothing to keep in sync by
hand.

| Runtime | Instruction file | Skills |
|---|---|---|
| Codex / Antigravity / OpenCode | `AGENTS.md` (read natively) | — / `.opencode/skills` |
| Claude Code | `CLAUDE.md` → `AGENTS.md` | `.claude/skills/*` → `.opencode/skills/**` |

- `../CLAUDE.md` is a symlink to `../AGENTS.md` — edit `AGENTS.md`, never the
  symlink (and note `AGENTS.md` is policy-protected).
- `skills/<name>` are symlinks onto the canonical skill library in
  `../.opencode/skills`. Add or rename a skill there only; the link is the
  Claude Code view of it. Claude Code discovers `SKILL.md` case-sensitively.

Drift (a renamed target, a skill linked on one side only, a re-added ban-risk
auth plugin) is caught by
`tests/tooling/test_agent_runtime_symlinks.py`.

Per-runtime mechanics (model routing, MCP servers, hooks, approval policy) are
intentionally **not** shared — they live in each tool's own config
(`.opencode/oh-my-openagent.json`, `opencode.json`, `.claude/settings*.json`,
`~/.codex/config.toml`).
