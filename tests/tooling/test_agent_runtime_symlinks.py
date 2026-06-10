"""Guard the multi-runtime agent-config bridge against drift.

The repo is wired so Claude Code, Codex, OpenCode, and the Gemini/Antigravity
CLI can all be opened in this checkout and start developing with the same
instructions, skills, and MCP tools:

* ``AGENTS.md`` is the single source of truth (read natively by Codex and
  OpenCode); ``CLAUDE.md`` and ``GEMINI.md`` symlink to it for Claude Code and
  the Gemini CLI.
* ``.claude/skills`` and ``.codex/skills`` are flat symlinks onto the canonical
  skill library in ``.opencode/skills`` so every runtime discovers the same
  SKILL.md files.
* The project MCP baseline ships in ``.mcp.json`` (Claude Code),
  ``opencode.json`` (OpenCode), and ``.gemini/settings.json`` (Gemini CLI).

These tests fail loudly if a link goes stale (renamed/removed target, a skill
added on one side only, a re-introduced ban-risk auth plugin or model provider,
a dropped MCP server, etc.).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENCODE_SKILLS = ROOT / ".opencode" / "skills"
# Runtimes that mirror the canonical .opencode skill library via flat symlinks
# (Claude Code reads .claude/skills, Codex reads .codex/skills — both project-
# level and discovered on clone).
MIRROR_SKILL_DIRS = {
    "claude": ROOT / ".claude" / "skills",
    "codex": ROOT / ".codex" / "skills",
}

# Auth plugins that borrow a first-party subscription OAuth seat inside a
# third-party client. Removed because that pattern risks account suspension;
# this list keeps them from silently creeping back into opencode.json.
BANNED_OPENCODE_PLUGINS = (
    "opencode-antigravity-auth",
    "opencode-openai-codex-auth",
)

# Model providers that OpenCode can only reach through a borrowed subscription
# OAuth seat (ChatGPT for `openai/*`, Antigravity for `google/*`). Routing any
# agent/category/default model at them re-introduces the suspension risk, so
# OpenCode is pinned to github-copilot (official OAuth) + api-key providers.
BANNED_MODEL_PROVIDER_PREFIXES = ("openai/", "google/")

# Project-level MCP baseline that ships in the repo so a fresh clone gets the
# same tool surface (not just whatever a machine happens to have configured
# globally). Claude Code reads it from .mcp.json, OpenCode from opencode.json,
# and the Gemini/Antigravity CLI from .gemini/settings.json. Codex only supports
# global (~/.codex) MCP, so it is covered out-of-band.
MCP_BASELINE = {"context7", "github", "basic-memory", "sequential-thinking"}


def _all_opencode_model_refs() -> dict[str, str]:
    """Collect every `model` string from opencode.json + oh-my-openagent.json."""
    refs: dict[str, str] = {}

    root_config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    if "model" in root_config:
        refs["opencode.json:model"] = root_config["model"]

    agent_config = json.loads(
        (ROOT / ".opencode" / "oh-my-openagent.json").read_text(encoding="utf-8")
    )
    for section in ("agents", "categories"):
        for name, body in agent_config.get(section, {}).items():
            if isinstance(body, dict) and "model" in body:
                refs[f"{section}.{name}"] = body["model"]
    return refs


def _opencode_leaf_skill_dirs() -> dict[str, Path]:
    """Map skill name -> leaf directory for every SKILL.md under .opencode."""
    leaves: dict[str, Path] = {}
    for skill_file in OPENCODE_SKILLS.rglob("SKILL.md"):
        leaf = skill_file.parent
        leaves[leaf.name] = leaf
    return leaves


def test_instruction_md_symlinks_to_agents_md() -> None:
    """Each runtime's entry-point doc is a symlink to the AGENTS.md source."""
    agents_md = ROOT / "AGENTS.md"
    assert agents_md.is_file()
    for entry in ("CLAUDE.md", "GEMINI.md"):
        link = ROOT / entry
        assert link.is_symlink(), f"{entry} must be a symlink, not a copy"
        # Relative target keeps the link portable across clones.
        assert os.readlink(link) == "AGENTS.md"
        assert link.resolve() == agents_md.resolve()


def test_instruction_mirrors_exempt_from_ssot_ownership_check() -> None:
    """The AGENTS.md mirrors must stay registered in the SSOT-ownership guard.

    Otherwise their mirrored content trips check4 (rule keyword without a
    cross-reference) and breaks CI.
    """
    from common.ssot import check_ssot_ownership

    for entry in ("CLAUDE.md", "GEMINI.md"):
        assert (ROOT / entry) in check_ssot_ownership.CHECK4_EXEMPT_PATHS


def test_every_opencode_skill_is_mirrored() -> None:
    """No skill exists on the OpenCode side without a link in each mirror."""
    leaves = _opencode_leaf_skill_dirs()
    assert leaves, "expected to discover .opencode/skills/**/SKILL.md leaves"

    for runtime, skills_dir in MIRROR_SKILL_DIRS.items():
        for name, leaf in sorted(leaves.items()):
            link = skills_dir / name
            assert link.is_symlink(), f"{runtime}: {link} missing or not a symlink"
            assert link.resolve() == leaf.resolve(), (
                f"{runtime}: {link} resolves to {link.resolve()}, expected {leaf}"
            )
            assert (link / "SKILL.md").is_file(), (
                f"{runtime}: {link} does not expose a SKILL.md (case-sensitive)"
            )


def test_no_orphan_or_broken_mirror_skill_links() -> None:
    """Every mirror entry is a live symlink back into .opencode."""
    leaves = _opencode_leaf_skill_dirs()
    for runtime, skills_dir in MIRROR_SKILL_DIRS.items():
        for entry in sorted(skills_dir.iterdir()):
            assert entry.is_symlink(), f"{runtime}: {entry} should be a symlink"
            assert entry.exists(), (
                f"{runtime}: {entry} is a broken symlink -> {os.readlink(entry)}"
            )
            assert entry.name in leaves, (
                f"{runtime}: {entry.name} has no matching .opencode skill"
            )


def test_opencode_config_has_no_banrisk_auth_plugins() -> None:
    config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    plugins = config.get("plugin", [])
    for plugin in plugins:
        for banned in BANNED_OPENCODE_PLUGINS:
            assert banned not in plugin, (
                f"ban-risk auth plugin {banned!r} must not be re-added to "
                f"opencode.json (found {plugin!r})"
            )


def test_no_opencode_agent_routes_to_banrisk_provider() -> None:
    """Every OpenCode model must use github-copilot or an api-key provider."""
    refs = _all_opencode_model_refs()
    assert refs, "expected to find model references to validate"
    for location, model in sorted(refs.items()):
        for prefix in BANNED_MODEL_PROVIDER_PREFIXES:
            assert not model.startswith(prefix), (
                f"{location} routes to ban-risk provider {model!r}; OpenCode can "
                f"only reach {prefix}* via borrowed subscription OAuth. Re-point "
                f"it at github-copilot or an api-key provider."
            )


def test_claude_mcp_baseline_present() -> None:
    """Claude Code's .mcp.json ships the project MCP baseline."""
    cfg = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    servers = set(cfg.get("mcpServers", {}))
    missing = MCP_BASELINE - servers
    assert not missing, f".mcp.json missing baseline MCP servers: {sorted(missing)}"


def test_opencode_mcp_baseline_present() -> None:
    """OpenCode's opencode.json carries the same project MCP baseline."""
    cfg = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    servers = set(cfg.get("mcp", {}))
    missing = MCP_BASELINE - servers
    assert not missing, f"opencode.json missing baseline MCP servers: {sorted(missing)}"


def test_gemini_mcp_baseline_present() -> None:
    """The Gemini/Antigravity CLI's .gemini/settings.json carries the baseline."""
    cfg = json.loads((ROOT / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    servers = set(cfg.get("mcpServers", {}))
    missing = MCP_BASELINE - servers
    assert not missing, (
        f".gemini/settings.json missing baseline MCP servers: {sorted(missing)}"
    )


def test_claude_settings_enable_mcp_baseline() -> None:
    """Committed .claude/settings.json auto-approves the baseline for the project."""
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    enabled = set(cfg.get("enabledMcpjsonServers", []))
    missing = MCP_BASELINE - enabled
    assert not missing, (
        f".claude/settings.json does not enable baseline MCP servers: {sorted(missing)}"
    )
