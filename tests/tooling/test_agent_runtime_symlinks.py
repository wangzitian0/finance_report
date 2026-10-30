"""Guard the multi-runtime agent-config bridge against drift.

The repo is wired so Claude Code, Codex, OpenCode, and the Gemini/Antigravity
CLI can all be opened in this checkout and start developing with the same
instructions, skills, and MCP tools:

* ``AGENTS.md`` is the single source of truth. Codex, OpenCode and Claude Code
  read it natively. ``CLAUDE.md`` must not exist: it suppresses the native
  ``AGENTS.md`` load of Claude Code (dev_env#393). ``GEMINI.md`` symlinks to
  ``AGENTS.md`` for the Gemini CLI.
* ``.agents/skills``, ``.claude/skills`` and ``.codex/skills`` hold
  physical skill directories rendered from ``dev_env`` and pinned by
  ``.ws-publish/manifest.json`` (dev_env#348) so every runtime discovers the
  same SKILL.md files (agy and OpenCode read ``.agents/skills``).
* The project MCP baseline ships in ``.mcp.json`` (Claude Code),
  ``opencode.json`` (OpenCode), and ``.gemini/settings.json`` (Gemini CLI).

These tests fail loudly if a link or rendered skill file goes stale (hand-edited
or unmanifested skill file, a skill added on one side only, a re-introduced ban-risk
auth plugin or model provider, a dropped MCP server, etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / ".ws-publish" / "manifest.json"
CANONICAL_SKILLS = ROOT / ".agents" / "skills"
# Runtimes that receive physical skill directories rendered from dev_env and
# pinned by .ws-publish/manifest.json (Claude Code reads .claude/skills, Codex
# reads .codex/skills, agy and OpenCode read .agents/skills — all project-level
# and discovered on clone).
MIRROR_SKILL_DIRS = {
    "claude": ROOT / ".claude" / "skills",
    "codex": ROOT / ".codex" / "skills",
    "agents": ROOT / ".agents" / "skills",
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


def _manifest_skill_files(root: Path = ROOT) -> dict[str, str]:
    """Load the rendered skill file -> sha256 map from .ws-publish/manifest.json."""
    manifest = json.loads(
        (root / ".ws-publish" / "manifest.json").read_text(encoding="utf-8")
    )
    files = manifest.get("skills", {}).get("files", {})
    assert isinstance(files, dict) and files, (
        "expected non-empty skills.files in .ws-publish/manifest.json"
    )
    return {str(k): str(v) for k, v in files.items()}


def _canonical_leaf_skill_dirs(root: Path = ROOT) -> dict[str, Path]:
    """Map skill name -> leaf directory for every SKILL.md under .agents/skills.

    The rendered skill directories are flat, so a name is the whole address: two
    leaves sharing one would make the checks silently require only whichever was
    seen last.
    """
    leaves: dict[str, Path] = {}
    skills_root = root / ".agents" / "skills"
    for skill_file in sorted(skills_root.rglob("SKILL.md")):
        leaf = skill_file.parent
        assert leaf.name not in leaves, (
            f"Rendered skills {leaves.get(leaf.name)} and {leaf} share the name "
            f"{leaf.name!r}; the flat runtime directories can hold only one of them"
        )
        leaves[leaf.name] = leaf
    return leaves


def test_instruction_md_symlinks_to_agents_md() -> None:
    """AGENTS.md is the one real carrier, CLAUDE.md is absent, GEMINI.md links to AGENTS.md."""
    agents_md = ROOT / "AGENTS.md"
    assert agents_md.is_file() and not agents_md.is_symlink()
    # A CLAUDE.md file or link stops Claude Code from loading AGENTS.md natively (dev_env#393).
    # The root check covers an untracked file; a tracked CLAUDE.md in any directory also stops the load.
    assert not os.path.lexists(ROOT / "CLAUDE.md"), "CLAUDE.md must not exist"
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    tracked_claude_md = [
        p.decode() for p in tracked if p and Path(p.decode()).name == "CLAUDE.md"
    ]
    assert tracked_claude_md == [], (
        f"tracked CLAUDE.md files stop AGENTS.md loading: {tracked_claude_md}"
    )
    for entry in ("GEMINI.md",):
        link = ROOT / entry
        assert link.is_symlink(), f"{entry} must be a symlink, not a copy"
        # Relative target keeps the link portable across clones.
        assert os.readlink(link) == "AGENTS.md"
        assert link.resolve() == agents_md.resolve()


def test_instruction_mirrors_exempt_from_ssot_ownership_check() -> None:
    """GEMINI.md, the one AGENTS.md mirror, stays registered in the SSOT-ownership guard; CLAUDE.md does not.

    Otherwise their mirrored content trips check4 (rule keyword without a
    cross-reference) and breaks CI.
    """
    from common.meta.extension import check_ssot_ownership

    assert (ROOT / "GEMINI.md") in check_ssot_ownership.CHECK4_EXEMPT_PATHS
    assert (ROOT / "CLAUDE.md") not in check_ssot_ownership.CHECK4_EXEMPT_PATHS


def _verify_rendered_skills_match_manifest(root: Path = ROOT) -> None:
    """Verify every skill file in .ws-publish/manifest.json exists and matches sha256."""
    manifest_files = _manifest_skill_files(root)
    leaves = _canonical_leaf_skill_dirs(root)
    assert leaves, "expected to discover .agents/skills/**/SKILL.md leaves"

    mirror_dirs = {
        "claude": root / ".claude" / "skills",
        "codex": root / ".codex" / "skills",
        "agents": root / ".agents" / "skills",
    }

    for rel_str, expected_sha in sorted(manifest_files.items()):
        path = root / rel_str
        assert path.is_file() and not path.is_symlink(), (
            f"manifest skill file {rel_str} must exist as a physical file, not a symlink"
        )
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, (
            f"rendered skill file {rel_str} sha256 {actual_sha} != "
            f"manifest sha256 {expected_sha} (.ws-publish/manifest.json)"
        )

    for runtime, skills_dir in mirror_dirs.items():
        for name, leaf in sorted(leaves.items()):
            mirror_dir = skills_dir / name
            assert mirror_dir.is_dir() and not mirror_dir.is_symlink(), (
                f"{runtime}: {mirror_dir} must be a physical directory, not a symlink"
            )
            skill_md = mirror_dir / "SKILL.md"
            assert skill_md.is_file() and not skill_md.is_symlink(), (
                f"{runtime}: {mirror_dir} does not expose a physical SKILL.md"
            )
            for canonical_file in sorted(p for p in leaf.rglob("*") if p.is_file()):
                rel = canonical_file.relative_to(leaf)
                mirror_file = mirror_dir / rel
                assert mirror_file.is_file() and not mirror_file.is_symlink(), (
                    f"{runtime}: missing rendered file {mirror_file}"
                )
                mirror_rel = mirror_file.relative_to(root).as_posix()
                assert mirror_rel in manifest_files, (
                    f"{runtime}: {mirror_rel} is not recorded in .ws-publish/manifest.json"
                )
                assert mirror_file.read_bytes() == canonical_file.read_bytes(), (
                    f"{runtime}: {mirror_file} content drifts from {canonical_file}"
                )


def _verify_no_unmanifested_or_orphan_skill_files(root: Path = ROOT) -> None:
    """Verify no extra, unmanifested, or symlinked files exist in rendered skill directories."""
    manifest_files = _manifest_skill_files(root)
    leaves = _canonical_leaf_skill_dirs(root)
    mirror_dirs = {
        "claude": root / ".claude" / "skills",
        "codex": root / ".codex" / "skills",
        "agents": root / ".agents" / "skills",
    }

    on_disk_files: set[str] = set()
    for runtime, skills_dir in mirror_dirs.items():
        for entry in sorted(skills_dir.iterdir()):
            if entry.name == ".ws-agy-managed":
                continue
            assert entry.is_dir() and not entry.is_symlink(), (
                f"{runtime}: {entry} must be a physical directory, not a symlink"
            )
            assert entry.name in leaves, (
                f"{runtime}: {entry.name} is not in .ws-publish/manifest.json. "
                "Rendered skill directories are pinned by .ws-publish/manifest.json; "
                "anything else is drift."
            )
            leaf = leaves[entry.name]
            canonical_rels = {
                p.relative_to(leaf) for p in leaf.rglob("*") if p.is_file()
            }
            mirror_rels: set[Path] = set()
            for p in sorted(entry.rglob("*")):
                assert not p.is_symlink(), f"{runtime}: {p} must not be a symlink"
                if p.is_file():
                    mirror_rels.add(p.relative_to(entry))
                    rel_posix = p.relative_to(root).as_posix()
                    assert rel_posix in manifest_files, (
                        f"{runtime}: unmanifested file {rel_posix} not in .ws-publish/manifest.json"
                    )
                    on_disk_files.add(rel_posix)
            assert mirror_rels == canonical_rels, (
                f"{runtime}: {entry.name} file set {sorted(mirror_rels)} != "
                f"rendered {sorted(canonical_rels)}"
            )

    assert on_disk_files == set(manifest_files), (
        f"on-disk skill files {sorted(on_disk_files ^ set(manifest_files))} "
        "do not match .ws-publish/manifest.json"
    )


def test_every_canonical_skill_is_mirrored() -> None:
    """Every skill in .ws-publish/manifest.json exists as a matching physical file across all runtimes."""
    _verify_rendered_skills_match_manifest(ROOT)


def test_no_orphan_or_broken_mirror_skill_links() -> None:
    """Every rendered skill entry is a physical directory matching .ws-publish/manifest.json."""
    _verify_no_unmanifested_or_orphan_skill_files(ROOT)


def test_rendered_skill_drift_fails_closed(tmp_path: Path) -> None:
    """Counterfactual: hand-editing a rendered SKILL.md or adding an unmanifested file fails closed."""
    skill_text = "# Sample skill\n"
    skill_sha = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
    manifest_files: dict[str, str] = {}
    for prefix in (".agents/skills", ".claude/skills", ".codex/skills"):
        rel = f"{prefix}/audit/SKILL.md"
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(skill_text, encoding="utf-8")
        manifest_files[rel] = skill_sha

    manifest_dir = tmp_path / ".ws-publish"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"skills": {"files": manifest_files}}),
        encoding="utf-8",
    )

    _verify_rendered_skills_match_manifest(tmp_path)
    _verify_no_unmanifested_or_orphan_skill_files(tmp_path)

    # 1. Hand-edit one rendered SKILL.md -> sha256 mismatch must fail closed.
    claude_skill = tmp_path / ".claude/skills/audit/SKILL.md"
    claude_skill.write_text("# Hand-edited drift\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="manifest sha256"):
        _verify_rendered_skills_match_manifest(tmp_path)
    claude_skill.write_text(skill_text, encoding="utf-8")

    # 2. Add an unmanifested file -> orphan check must fail closed.
    extra_file = tmp_path / ".codex/skills/audit/extra.md"
    extra_file.write_text("orphan\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="unmanifested file"):
        _verify_no_unmanifested_or_orphan_skill_files(tmp_path)


def test_opencode_config_has_no_banrisk_auth_plugins() -> None:
    config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    plugins = config.get("plugin", [])
    assert isinstance(plugins, list), "opencode.json plugin field must be a list"
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
    """If tracked, .claude/settings.json auto-approves the baseline for the project."""
    proc = subprocess.run(
        ["git", "ls-files", ".claude/settings.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if not proc.stdout.strip():
        # Untracked and ignored per #2105; developer-local workstation file is unconstrained
        return
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    enabled = set(cfg.get("enabledMcpjsonServers", []))
    missing = MCP_BASELINE - enabled
    assert not missing, (
        f".claude/settings.json does not enable baseline MCP servers: {sorted(missing)}"
    )


def _assert_claude_settings_untracked(tracked_output: str) -> None:
    assert tracked_output == "", (
        f".claude/settings.json is tracked in git index: {tracked_output!r}. "
        "It must be untracked (git rm --cached) and ignored to avoid leaking private paths."
    )


def test_claude_settings_not_tracked_and_no_symlink_staged() -> None:
    """Issue #2105: .claude/settings.json must not be tracked in git.

    If tracked (e.g. via git add -A staging a local workstation symlink -> /Users/...),
    it exposes developer machine paths to public history and breaks fresh clones.
    Any tracked symlink for .claude/settings.json or any git tracking of it fails closed.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-s", ".claude/settings.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    _assert_claude_settings_untracked(proc.stdout.strip())


def test_claude_settings_tracked_symlink_fails_closed() -> None:
    """Counterfactual: detecting a tracked symlink or any git index entry must fail closed."""
    fake_output = (
        "120000 4b825dc642cb6eb9a060e54bf8d69288fbee4904 0\t.claude/settings.json"
    )
    with pytest.raises(AssertionError, match="tracked in git index"):
        _assert_claude_settings_untracked(fake_output)


# Explicit `tools/<x>.py` path — must exist at exactly that path.
_TOOL_PATH_REF = re.compile(r"\btools/[A-Za-z0-9_./-]+\.py\b")
# Bare backticked `<name>.py` (no path) — skills often cite a tool script by
# filename alone (e.g. a preflight mapping cell). Those must still resolve to a
# real file somewhere in the repo, or the same drift slips past a path-only check.
_BARE_PY_REF = re.compile(r"`([A-Za-z0-9_-]+\.py)`")
_PY_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "worktrees"}


def _repo_py_basenames() -> set[str]:
    """All `*.py` basenames tracked in the repo (heavy/vendored dirs pruned)."""
    names: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _PY_SKIP_DIRS]
        names.update(fn for fn in filenames if fn.endswith(".py"))
    return names


_COMMON_ENGINEERING_SKILLS = {
    "audit",
    "close",
    "codegraph",
    "deploy-evidence",
    "prr",
    "recall",
    "smoke",
    "ssot",
    "start",
}


def test_skill_docs_reference_existing_tools() -> None:
    """Every tool script a canonical SKILL.md tells agents to run must resolve.

    Skills are static markdown; when a tool is renamed or moved, nothing fails the
    skill until an agent follows a now-dead command. Two citation styles are checked:

    * explicit ``tools/<x>.py`` paths must exist at that path;
    * bare backticked ``<name>.py`` filenames (no path) must match a real ``*.py``
      file somewhere in the repo.

    (This guard exists because the ac-workflow and preflight skills both shipped
    references to ``check_ac_traceability.py`` — which never existed; the real gate
    is ``check_ac_index.py`` — and the bare-filename form slipped past a path-only
    matcher.)
    """
    repo_basenames = _repo_py_basenames()
    skill_mds = sorted(CANONICAL_SKILLS.rglob("SKILL.md"))
    assert skill_mds, f"expected canonical SKILL.md files under {CANONICAL_SKILLS}"
    missing: list[str] = []
    for skill_md in skill_mds:
        if skill_md.parent.name in _COMMON_ENGINEERING_SKILLS:
            continue
        text = skill_md.read_text(encoding="utf-8")
        rel = skill_md.relative_to(ROOT)
        for ref in _TOOL_PATH_REF.findall(text):
            if not (ROOT / ref).is_file():
                missing.append(f"{rel} -> {ref}")
        for name in _BARE_PY_REF.findall(text):
            if name not in repo_basenames:
                missing.append(f"{rel} -> {name} (no such file in repo)")
    assert not missing, (
        f"SKILL.md files reference non-existent tools: {sorted(set(missing))}"
    )


def _is_ignored(path: str) -> bool:
    """Ask git whether path is ignored. Exit 0 means ignored, 1 means not ignored."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True
    )
    assert result.returncode in (0, 1), result.stderr.decode()
    return result.returncode == 0


def test_agent_run_artifacts_are_ignored_and_skills_stay_tracked() -> None:
    """Issue #2445: .agents/runs/ holds run artifacts and is ignored; .agents/skills is tracked.

    An untracked .agents/runs/ makes the delivery check report a dirty tree, and a
    `git add -A` can commit run logs.
    """
    assert _is_ignored(".agents/runs/issue1/probe.log"), (
        ".agents/runs/ is not ignored: run artifacts make the working tree dirty"
    )
    assert not _is_ignored(".agents/skills/example/SKILL.md"), (
        ".agents/skills must stay tracked: do not ignore all of .agents/"
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", ".agents/skills"], cwd=ROOT, text=True
    )
    assert tracked.strip(), "no tracked file under .agents/skills"
