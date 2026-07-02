"""Server-side OpenPanel product-analytics emitter (BE->OpenPanel).

The backend half of the OpenPanel integration. Why a thin REST client and NOT the
official ``openpanel`` Python SDK (which the frontend's ``@openpanel/nextjs`` mirrors)?

  The only published ``openpanel`` PyPI package is v0.0.1 and it ALWAYS sends
  ``"profileId": null`` in the track payload. Our self-hosted OpenPanel validates
  the body with Zod and rejects null (``Expected string, received null`` -> HTTP 400),
  and the SDK gives no way to omit the field. Proven against the live instance: the
  SDK payload 400s; the same payload without ``profileId`` is accepted (200). So the
  SDK is non-functional here and the documented HTTP ``/track`` contract is the only
  working server-side path. Revisit if OpenPanel ships a fixed Python SDK.

Why a backend emitter at all (the frontend already tracks)? Server-side events are
*authoritative* — they fire from the backend regardless of the browser (adblock /
no-JS / closed tab), so a conversion the server actually completed is never
under-counted. Complements, not replaces, the FE analytics.

Config-gated (no ``OPENPANEL_CLIENT_ID`` => complete no-op), non-blocking (the POST
runs on a daemon thread so it never sits on the request's critical path), and never
raises — analytics can never break a request. Our OpenPanel clients are
``ignoreCorsAndSecret=true``, so the public client-id alone authorizes the write.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import src.config

# Bound from the bare published root (see logger.py; config publishes no names).
settings = src.config.settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


def is_configured() -> bool:
    """True when a per-env OpenPanel project is wired (client-id + api url)."""
    return bool((settings.openpanel_client_id or "").strip() and (settings.openpanel_api_url or "").strip())


def _track_endpoint() -> str:
    return (settings.openpanel_api_url or "").strip().rstrip("/") + "/track"


def build_payload(event: str, properties: dict[str, Any] | None) -> dict[str, Any]:
    """OpenPanel ``/track`` body. ``source=backend`` distinguishes server-side events
    from browser ones; ``deployment_environment`` carries the env for per-env filtering.
    Deliberately omits ``profileId`` — our OpenPanel rejects a null one (module docstring)."""
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


def _post(payload: dict[str, Any], client_id: str, endpoint: str) -> None:
    """Best-effort single POST. Never raises — a telemetry hiccup must not surface."""
    try:
        # Imported lazily: this module is loaded via the observability package
        # root, which tooling-only environments import without backend deps.
        import httpx

        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.post(endpoint, json=payload, headers={"openpanel-client-id": client_id})
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — analytics must never break a request
        logger.debug("OpenPanel backend track failed for %r: %s", payload.get("payload", {}).get("name"), exc)


def track(event: str, properties: dict[str, Any] | None = None) -> bool:
    """Emit one OpenPanel event from the backend. Returns True if dispatched.

    Config-gated (no-op + False when no project is wired). The HTTP POST runs on a
    daemon thread so this is safe to call inline from an async request handler without
    blocking the event loop or the response, and it never raises.
    """
    client_id = (settings.openpanel_client_id or "").strip()
    if not is_configured():
        return False
    payload = build_payload(event, properties)
    threading.Thread(
        target=_post,
        args=(payload, client_id, _track_endpoint()),
        daemon=True,
    ).start()
    return True
