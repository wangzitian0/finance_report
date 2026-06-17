"""Server-side OpenPanel product-analytics emitter (BE→OpenPanel).

Mirrors the frontend ``src/lib/analytics.ts`` contract — a thin, config-gated,
NON-BLOCKING, never-throws wrapper over the OpenPanel HTTP ``/track`` API.

Why a backend emitter at all (the frontend already tracks)? Server-side events
are *authoritative*: they fire from the backend regardless of the browser
(adblock / no-JS / closed tab), so a conversion the server actually completed
(e.g. a report package persisted) is never under-counted. This complements,
not replaces, the FE analytics.

Config-gated: when ``OPENPANEL_CLIENT_ID`` is unset (local / CI / preview without
a project) every call is a complete no-op — same posture as the FE SDK and the
OTel exporter. Failures are swallowed so analytics can never break a request.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# Analytics is best-effort telemetry, never on the request's critical path.
_TIMEOUT_SECONDS = 5.0


def is_configured() -> bool:
    """True when a per-env OpenPanel project is wired (client-id + api url)."""
    return bool((settings.openpanel_client_id or "").strip() and (settings.openpanel_api_url or "").strip())


def _track_endpoint() -> str:
    base = (settings.openpanel_api_url or "").strip().rstrip("/")
    return f"{base}/track"


def _build_payload(event: str, properties: dict[str, Any] | None) -> dict[str, Any]:
    """OpenPanel /track body. `source=backend` distinguishes server-side events
    from the browser ones; `deployment.environment` carries the env so events are
    filterable per env (mirrors the OTel resource attribute + the FE contract)."""
    env = (settings.openpanel_environment or "").strip() or settings.environment
    return {
        "type": "track",
        "payload": {
            "name": event,
            "properties": {
                "source": "backend",
                "deployment_environment": env,
                **(properties or {}),
            },
        },
    }


async def track(event: str, properties: dict[str, Any] | None = None) -> bool:
    """Emit one OpenPanel event from the backend. Returns True if dispatched.

    Config-gated (no-op + False when no project is wired) and NEVER raises — any
    transport/HTTP error is logged at debug and swallowed so a telemetry hiccup
    cannot fail the caller's request. Best paired with FastAPI ``BackgroundTasks``
    so it runs after the response is sent.
    """
    client_id = (settings.openpanel_client_id or "").strip()
    if not client_id or not (settings.openpanel_api_url or "").strip():
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _track_endpoint(),
                json=_build_payload(event, properties),
                headers={"openpanel-client-id": client_id},
            )
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — analytics must never break a request
        logger.debug("OpenPanel backend track failed for %r: %s", event, exc)
        return False
