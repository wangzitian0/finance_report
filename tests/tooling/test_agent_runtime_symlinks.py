"""Guard the multi-runtime agent-config bridge against drift.

The repo is wired so that Antigravity, Codex, and Claude Code can all be opened
in this checkout and start developing with the same instructions and skills:

* ``AGENTS.md`` is the single source of truth (read natively by Codex,
  Antigravity, and OpenCode).
* ``CLAUDE.md`` is a symlink to ``AGENTS.md`` so Claude Code reads the same doc.
* ``.claude/skills/<name>`` are symlinks onto the canonical skill library in
  ``.opencode/skills`` so Claude Code discovers the exact same SKILL.md files
  that OpenCode uses.

These tests fail loudly if a link goes stale (renamed/removed target, a new
skill added on one side only, a re-introduced ban-risk auth plugin, etc.).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENCODE_SKILLS = ROOT / ".opencode" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"

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


def test_claude_md_symlinks_to_agents_md() -> None:
    claude_md = ROOT / "CLAUDE.md"
    agents_md = ROOT / "AGENTS.md"

    assert claude_md.is_symlink(), "CLAUDE.md must be a symlink, not a copy"
    # Relative target keeps the link portable across clones.
    assert os.readlink(claude_md) == "AGENTS.md"
    assert agents_md.is_file()
    assert claude_md.resolve() == agents_md.resolve()


def test_claude_md_is_exempt_from_ssot_ownership_check() -> None:
    """The CLAUDE.md mirror must stay registered in the SSOT-ownership guard.

    Otherwise its mirrored AGENTS.md content trips check4 (rule keyword without
    a cross-reference) and breaks CI.
    """
    from common.ssot import check_ssot_ownership

    assert (ROOT / "CLAUDE.md") in check_ssot_ownership.CHECK4_EXEMPT_PATHS


def test_every_opencode_skill_has_a_claude_symlink() -> None:
    """No skill exists on the OpenCode side without a Claude Code link."""
    leaves = _opencode_leaf_skill_dirs()
    assert leaves, "expected to discover .opencode/skills/**/SKILL.md leaves"

    for name, leaf in sorted(leaves.items()):
        link = CLAUDE_SKILLS / name
        assert link.is_symlink(), f".claude/skills/{name} missing or not a symlink"
        assert link.resolve() == leaf.resolve(), (
            f".claude/skills/{name} resolves to {link.resolve()}, expected {leaf}"
        )
        assert (link / "SKILL.md").is_file(), (
            f".claude/skills/{name} does not expose a SKILL.md (case-sensitive)"
        )


def test_no_orphan_or_broken_claude_skill_links() -> None:
    """Every .claude/skills entry is a live symlink back into .opencode."""
    leaves = _opencode_leaf_skill_dirs()
    for entry in sorted(CLAUDE_SKILLS.iterdir()):
        assert entry.is_symlink(), f"{entry} should be a symlink"
        assert entry.exists(), f"{entry} is a broken symlink -> {os.readlink(entry)}"
        assert entry.name in leaves, (
            f".claude/skills/{entry.name} has no matching .opencode skill"
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
