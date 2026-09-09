"""AC-runtime.env-empty-values.1 — no shipped artifact ships an empty value for
an env name that participates in a ``Settings`` alias chain.

Why the gate exists: ``Settings`` does not set ``env_ignore_empty``, so an empty
environment value is a *value*, not "unset". Where a field's ``validation_alias``
is an ``AliasChoices`` chain, the first name **present** wins — so an artifact
that ships ``ZAI_API_KEY=`` silently shadows the ``GEMINI_API_KEY`` a developer
did fill in, and the app runs with AI off for no visible reason.

The alias names are derived from the generated required-env manifest
(``common/runtime/required-env.generated.json``, whose ``aliases`` field mirrors
``config.py``), so a chain added later is covered without editing this file.

Making an empty value mean "unset" at the model level is deliberately **not**
this gate's job — see the ``env_ignore_empty`` issue referenced from
``common/runtime/readme.md``. Until that lands, the only defence is that no
artifact produces an empty value in the first place.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "common" / "runtime" / "required-env.generated.json"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

# ``${VAR}`` (no default -> empty when unset), ``${VAR:-}`` / ``${VAR-}`` and the
# quoted-empty-default spellings all materialize an empty string in the container.
# ``${VAR:-value}`` and ``${VAR:?message}`` cannot, so they are not matched.
_EMPTY_EXPANSION_RE = re.compile(
    r"""^\$\{[A-Za-z_][A-Za-z0-9_]*(?::?-\s*(?:""|'')?)?\}$"""
)
_DOTENV_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$"
)


def _alias_chain_env_names() -> set[str]:
    """Every env name that competes inside an ``AliasChoices`` chain."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for entry in manifest["fields"]:
        aliases = entry.get("aliases") or []
        if aliases:
            names.add(entry["env"])
            names.update(aliases)
    return names


def _materializes_empty(value: object) -> bool:
    """True when this compose/dotenv right-hand side can yield an empty string.

    ``None`` is the compose pass-through form (``KEY:`` in map syntax, ``- KEY``
    in list syntax): the variable reaches the container only when the environment
    Compose runs with actually has it, and is omitted entirely otherwise. That is
    the shape this gate wants, so it is never a violation.
    """
    if value is None:
        return False
    text = str(value).strip()
    if text in ("", '""', "''"):
        return True
    return bool(_EMPTY_EXPANSION_RE.match(text))


def _dotenv_empty_assignments(path: Path, names: set[str]) -> list[str]:
    """Uncommented ``NAME=`` lines (empty literal) for a watched name."""
    findings: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # a commented example documents the key without assigning it
        match = _DOTENV_ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        name, raw_value = match.group(1), match.group(2)
        if name in names and _materializes_empty(raw_value):
            findings.append(f"{path.name}:{number}: {line.strip()}")
    return findings


def _compose_environment_blocks(node: object, where: str) -> list[tuple[str, object]]:
    """Every ``environment:`` value in the document (services, anchors, x- keys)."""
    blocks: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "environment":
                blocks.append((where, value))
            else:
                blocks.extend(_compose_environment_blocks(value, f"{where}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            blocks.extend(_compose_environment_blocks(item, f"{where}[{index}]"))
    return blocks


def _compose_empty_assignments(path: Path, names: set[str]) -> list[str]:
    """Compose ``environment`` entries that materialize an empty value."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    findings: list[str] = []
    for where, block in _compose_environment_blocks(document, path.name):
        pairs: list[tuple[str, object]] = []
        if isinstance(block, dict):
            pairs = list(block.items())
        elif isinstance(block, list):
            for item in block:
                text = str(item)
                if "=" not in text:
                    continue  # pass-through form: nothing is materialized
                key, _, value = text.partition("=")
                pairs.append((key.strip(), value))
        for name, value in pairs:
            if name in names and _materializes_empty(value):
                findings.append(f"{where}: {name}: {value!r}")
    return findings


def _shipped_compose_files() -> list[Path]:
    return sorted(ROOT.glob("docker-compose*.yml"))


def test_AC_runtime_env_empty_values_1_no_artifact_ships_an_empty_alias_chain_value() -> (
    None
):
    """AC-runtime.env-empty-values.1: `.env.example` and the root compose files
    never assign an empty value to an alias-chain env name."""
    names = _alias_chain_env_names()
    assert "ZAI_API_KEY" in names and "GEMINI_API_KEY" in names, (
        "the ai_api_key alias chain vanished from the generated manifest — "
        "this gate would be scanning for nothing"
    )

    compose_files = _shipped_compose_files()
    assert compose_files, "expected root docker-compose*.yml files to scan"

    findings = _dotenv_empty_assignments(ENV_EXAMPLE_PATH, names)
    for compose_file in compose_files:
        findings.extend(_compose_empty_assignments(compose_file, names))

    assert not findings, (
        "a shipped artifact assigns an empty value to an env name that competes "
        "in a Settings alias chain. An empty value is NOT 'unset' today "
        "(Settings has no env_ignore_empty), so it shadows every later alias in "
        "the chain. Ship a commented example in .env.example, and the "
        "pass-through form (`KEY:` / `- KEY`) in compose:\n  " + "\n  ".join(findings)
    )


def test_the_detectors_still_recognise_every_empty_producing_spelling(
    tmp_path: Path,
) -> None:
    """Red-team the parsers: the gate above is only worth its green if these
    spellings are still caught (a broken parser would make it vacuous)."""
    names = {"WATCHED", "WATCHED_ALIAS"}

    dotenv = tmp_path / ".env.example"
    dotenv.write_text(
        "\n".join(
            [
                "# WATCHED=",  # commented example — allowed
                "WATCHED_ALIAS=real-value",  # non-empty — allowed
                "UNWATCHED=",  # not in a chain — out of scope
                "WATCHED=",  # violation
                'export WATCHED_ALIAS=""',  # violation
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dotenv_findings = _dotenv_empty_assignments(dotenv, names)
    assert len(dotenv_findings) == 2, dotenv_findings
    assert all("UNWATCHED" not in finding for finding in dotenv_findings)

    compose = tmp_path / "docker-compose.probe.yml"
    compose.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "ok-map": {"environment": {"WATCHED": None}},
                    "ok-list": {"environment": ["WATCHED"]},
                    "ok-default": {"environment": {"WATCHED": "${WATCHED:-real}"}},
                    "ok-required": {"environment": {"WATCHED": "${WATCHED:?set me}"}},
                    "bad-empty-default": {"environment": {"WATCHED": "${WATCHED:-}"}},
                    "bad-dash-default": {"environment": {"WATCHED": "${WATCHED-}"}},
                    "bad-bare-expansion": {"environment": {"WATCHED": "${WATCHED}"}},
                    "bad-literal": {"environment": {"WATCHED_ALIAS": ""}},
                    "bad-list": {"environment": ["WATCHED_ALIAS=${WATCHED_ALIAS:-}"]},
                }
            }
        ),
        encoding="utf-8",
    )
    compose_findings = _compose_empty_assignments(compose, names)
    assert len(compose_findings) == 5, compose_findings
    # Only the bad-* services contribute; every ok-* spelling stays silent.
    assert all(".services.bad-" in finding for finding in compose_findings), (
        compose_findings
    )
