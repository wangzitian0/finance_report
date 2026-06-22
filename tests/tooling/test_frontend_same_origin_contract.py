"""AC7.12.8 (G1, #898) — the published front-end ``:<sha>`` image is environment-independent.

promote-not-rebuild requires the published image to carry **no** environment domain.
The front end calls the API same-origin (relative ``/api``), so one image works on
staging and prod unchanged. A concrete environment domain baked into the publish build
(``NEXT_PUBLIC_API_URL`` / ``NEXT_PUBLIC_APP_URL``) couples the artifact to a single
environment and breaks promote-not-rebuild — see EPIC-007 AC7.12.8, Known risk H1.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# A concrete absolute host assigned to NEXT_PUBLIC_(API|APP)_URL is baked into the
# bundle at `next build` time and ties the published image to that one environment.
# Match `=` or `:` assignment with optional surrounding quotes, so a quoted YAML value
# (NEXT_PUBLIC_API_URL="https://...") cannot slip past (Copilot CR on #901).
_BAKED_ENV_DOMAIN = re.compile(
    r"""NEXT_PUBLIC_(?:API|APP)_URL\s*[=:]\s*["']?\s*https?://"""
)

# Files that contribute to the *published* image. deploy.yml is intentionally
# excluded — its build-on-missing path is the deploy-side escape hatch owned by P1b/P2.
_PUBLISH_BUILD_SOURCES = (".github/workflows/ci.yml", "apps/frontend/Dockerfile")


def test_AC7_12_8_published_frontend_image_has_no_baked_env_domain():
    offenders = {
        src: hits
        for src in _PUBLISH_BUILD_SOURCES
        if (hits := _BAKED_ENV_DOMAIN.findall(read(src)))
    }
    assert not offenders, (
        "The published :<sha> front-end image bakes an environment domain into the "
        "bundle, coupling the artifact to one environment and breaking promote-not-rebuild "
        f"(AC7.12.8, G1 #898). Found: {offenders}. "
        "Leave NEXT_PUBLIC_API_URL unset so the front end uses the same-origin relative /api path."
    )


# Accept `||` or `??` and either quote style, so behaviour-preserving edits don't
# break the contract while the same-origin fallback itself stays enforced (Copilot CR).
_SAME_ORIGIN_FALLBACK = re.compile(
    r"""NEXT_PUBLIC_API_URL\s*(?:\|\||\?\?)\s*(?:""|'')"""
)


def test_AC7_12_8_frontend_api_keeps_same_origin_fallback():
    # The same-origin fallback is the invariant that makes the image env-independent;
    # lock it so a future edit cannot silently reintroduce an absolute API base.
    api = read("apps/frontend/src/lib/api.ts")
    assert _SAME_ORIGIN_FALLBACK.search(api), (
        "API_URL must fall back to an empty string (relative same-origin /api) when "
        "NEXT_PUBLIC_API_URL is unset (AC7.12.8, G1 #898)."
    )
