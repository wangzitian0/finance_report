"""The two SHA-256 digest definitions of the backend (#2768).

A digest is stored data: trace records, command digests and result ids keep these
values. Both functions keep the exact bytes of the private copies that they replaced.
Do not change the separators, the sort order, the encoding or the text.

* ``canonical_json_digest`` hashes the canonical JSON text of one value.
* ``text_digest`` hashes one string as it is.

``canonical_json_digest("x")`` is not ``text_digest("x")``: the canonical text of a
string has quotes. ``text_digest(json.dumps(value, sort_keys=True, separators=(",", ":")))``
equals ``canonical_json_digest(value)``.

``canonical_json_digest`` encodes JSON values only. A value that JSON cannot encode (for
example a ``datetime``) raises ``TypeError`` unless the caller passes ``default``, which goes
to ``json.dumps`` unchanged. A caller passes ``default=str`` only where the code that it
replaced did so.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any


def canonical_json_digest(value: object, *, default: Callable[[Any], Any] | None = None) -> str:
    """Return the SHA-256 hex digest of the canonical JSON text of ``value``."""
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)
    return hashlib.sha256(serialized.encode()).hexdigest()


def text_digest(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()
