# Multi-runtime agent bridge

This repo is open-and-develop for **Claude Code**, **Codex**, **OpenCode**, and
the **Gemini / Antigravity CLI**. `AGENTS.md` is the authoritative entry point
(`GEMINI.md` symlinks to `AGENTS.md`; no `CLAUDE.md` may exist, `dev_env#393`).
`.agents/skills`, `.claude/skills`, and `.codex/skills` are physical skill
directories rendered from `dev_env` and pinned by `.ws-publish/manifest.json`
(`dev_env#348`). Do not hand-edit rendered skill files; edit their `dev_env`
sources and run `ws-render-pr finance_report`. A few small committed config
files (`.claude/settings.json`, `.mcp.json`, `.gemini/settings.json`,
`opencode.json`) declare per-runtime MCP/approval.

| Runtime | Instructions | Skills | MCP |
|---|---|---|---|
| OpenCode | `AGENTS.md` (native) | `.agents/skills/*` (rendered from `dev_env`) | `opencode.json` |
| Claude Code | `AGENTS.md` (native; no `CLAUDE.md` may exist, dev_env#393) | `.claude/skills/*` (rendered from `dev_env`) | `.mcp.json` |
| Codex | `AGENTS.md` (native) | `.codex/skills/*` (rendered from `dev_env`) | global only |
| Gemini / Antigravity | `GEMINI.md` → `AGENTS.md` | `.agents/skills/*` (rendered from `dev_env`) | `.gemini/settings.json` |

- `../GEMINI.md` is a symlink to `../AGENTS.md`. A `CLAUDE.md` in any directory stops Claude Code from loading `AGENTS.md`, so none exists. Edit
  `AGENTS.md` via its `dev_env` source, never the symlink (and note `AGENTS.md` is policy-protected).
- `.agents/skills/<name>`, `.claude/skills/<name>`, and `.codex/skills/<name>`
  are physical skill directories rendered from `dev_env` and pinned by
  `.ws-publish/manifest.json` (`dev_env#348`). Do not hand-edit rendered skill
  files; edit their `dev_env` sources and run `ws-render-pr finance_report`.
  Discovery is case-sensitive (`SKILL.md`), and all runtimes pick up project
  skills on clone.

Drift (a hand-edited or unmanifested skill file, a skill rendered on one side only, a re-added ban-risk
auth plugin or model provider, a dropped MCP server) is caught by
`tests/tooling/test_agent_runtime_symlinks.py`.

Per-runtime mechanics (model routing, hooks, approval policy) are intentionally
**not** shared — they live in each tool's own config
(`.opencode/oh-my-openagent.json`, `opencode.json`, `.claude/settings*.json`,
`~/.codex/config.toml`).

## Claude Code subagents (`.claude/agents/`)

OpenCode's named agents live in `.opencode/oh-my-openagent.json` (a JSON config,
not per-agent files), so they **cannot** be rendered into Claude Code as
per-agent files. Claude Code subagents are individual markdown files with their own
`model:` routing. `.claude/agents/` therefore holds a small Claude-native mirror
of the cost-tiered roles — this is per-runtime mechanics, intentionally not
shared:

| Agent | Model | Role |
|---|---|---|
| `explore` | `haiku` | cheap/fast read-only codebase search (fan-out) |
| `librarian` | `haiku` | external docs / web / library version lookup |
| `oracle` | `opus` | deep architecture & design reasoning (advisory) |

The main loop (session model) is the orchestrator — no file needed. Built-in
`Explore`/`Plan`/`general-purpose` and plugin agents remain available; these just
pin a default model per role so search fan-out doesn't run on the expensive
session model. Tune models here, not in the shared `AGENTS.md`.

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

`github` needs a `GITHUB_PAT` environment variable. Use a least-privilege
**fine-grained** PAT scoped to only the repos you need, with read-only
permissions unless an action requires write; avoid classic broad-scope tokens.
It is referenced as `${GITHUB_PAT}` and never committed. The baseline is
drift-guarded by `tests/tooling/test_agent_runtime_symlinks.py`.

Work-environment MCP servers (Skynet, etc.) are deliberately kept out of the
project baseline — they live in personal global config only.
