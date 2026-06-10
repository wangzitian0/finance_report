# Multi-runtime agent bridge

This repo is open-and-develop for **Claude Code**, **Codex**, **OpenCode**, and
the **Gemini / Antigravity CLI**. The single source of truth is `AGENTS.md`;
everything else is a symlink, so there is nothing to keep in sync by hand.

| Runtime | Instructions | Skills | MCP |
|---|---|---|---|
| OpenCode | `AGENTS.md` (native) | `.opencode/skills` (canonical) | `opencode.json` |
| Claude Code | `CLAUDE.md` → `AGENTS.md` | `.claude/skills/*` → `.opencode/skills/**` | `.mcp.json` |
| Codex | `AGENTS.md` (native) | `.codex/skills/*` → `.opencode/skills/**` | global only |
| Gemini / Antigravity | `GEMINI.md` → `AGENTS.md` | (via `AGENTS.md`) | `.gemini/settings.json` |

- `../CLAUDE.md` and `../GEMINI.md` are symlinks to `../AGENTS.md` — edit
  `AGENTS.md`, never the symlinks (and note `AGENTS.md` is policy-protected).
- `.claude/skills/<name>` and `.codex/skills/<name>` are flat symlinks onto the
  canonical library in `../.opencode/skills`. Add or rename a skill **there
  only**; the links are each runtime's view of it. Discovery is case-sensitive
  (`SKILL.md`), and both Claude Code and Codex pick up project skills on clone.

Drift (a renamed target, a skill linked on one side only, a re-added ban-risk
auth plugin or model provider, a dropped MCP server) is caught by
`tests/tooling/test_agent_runtime_symlinks.py`.

Per-runtime mechanics (model routing, hooks, approval policy) are intentionally
**not** shared — they live in each tool's own config
(`.opencode/oh-my-openagent.json`, `opencode.json`, `.claude/settings*.json`,
`~/.codex/config.toml`).

## MCP baseline

So a fresh clone gets the same tool surface — not just whatever a machine
happens to have configured globally — the project ships an MCP baseline:

| Server | Purpose |
|---|---|
| `context7` | up-to-date library/framework docs |
| `github` | PRs, CI, issues (remote Copilot MCP) |
| `basic-memory` | cross-session notes |
| `sequential-thinking` | structured reasoning scaffold |

- **Claude Code** reads `../.mcp.json`; the committed `settings.json` lists these
  in `enabledMcpjsonServers` so they are pre-approved for this project.
- **OpenCode** reads the same set from `../opencode.json` (`mcp`).
- **Gemini / Antigravity CLI** reads the same set from `../.gemini/settings.json`.
- **Codex** only supports global MCP (`~/.codex/config.toml`); it cannot read a
  repo-level baseline, so configure it there once per machine. (Codex *skills*,
  unlike its MCP, are project-level via `.codex/skills`.)

`github` needs a `GITHUB_PAT` environment variable (a GitHub PAT with repo +
read scopes); it is referenced as `${GITHUB_PAT}` and never committed. The
baseline is drift-guarded by `tests/tooling/test_agent_runtime_symlinks.py`.

Work-environment MCP servers (Skynet, etc.) are deliberately kept out of the
project baseline — they live in personal global config only.
