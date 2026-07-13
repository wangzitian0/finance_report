"""Eager model discovery — import every model module for its registration side effect.

Importing a model module runs its class definitions, which register the mapped
classes on ``src.database.Base.metadata``. SQLAlchemy needs *all* models loaded
before ``Base.metadata.create_all`` (test schema build) or Alembic autogenerate
can see the full schema, and before cross-module string relationships can be
configured.

This module replaces the former ``src.models._registry`` (issue #1461,
AC-meta.facade.*, dissolved #1675 D6 — the final models-decentralization
slice). Discovery sites import this module explicitly:

* ``migrations/env.py``      — Alembic autogenerate target metadata
* ``tests/conftest.py``      — per-worker ``create_all`` schema build
* ``src/main.py``            — eager mapper registration at app startup
* ``common/meta/extension/generate_db_schema_reference.py`` — schema reference generation

This is NOT a re-export facade: it publishes no symbols (``__all__`` is empty).
Other code must import each model from its owning package's published root
(``from src.extraction import AtomicTransaction``), never from here.
"""

from __future__ import annotations

# Every package that owns ORM entities registers its mappers on
# Base.metadata via its published root import; importing each root is the
# whole side effect (#1675 — the fact family, statement envelope, and every
# other domain's ORM all moved out of the former src/models/).
import src.advisor  # noqa: F401,E402
import src.extraction  # noqa: F401,E402
import src.ledger  # noqa: F401,E402
import src.llm  # noqa: F401,E402
import src.platform  # noqa: F401,E402
import src.portfolio  # noqa: F401,E402
import src.pricing  # noqa: F401,E402
import src.reconciliation  # noqa: F401,E402

# identity exposes its published surface lazily (PEP 562 __getattr__, so
# importing the package doesn't eagerly pull the FastAPI transport layer);
# accessing a published name triggers its SQL adapter's import as a side
# effect, registering User/AiFeedback on Base.metadata the same way the
# eager-import packages above register theirs. `import src.identity` alone
# would NOT trigger this (the lazy root does nothing at import time), and
# `import src.identity.extension.sql` (a deep, unpublished-internal import)
# would cross the app-boundary gate from this app-remainder module — so the
# published-name form is both the correct trigger and the boundary-clean one.
from src.identity import AiFeedback as _AiFeedback, User as _User  # noqa: F401,E402

# observability publishes its one ORM class lazily (importing its root must
# stay light for logging consumers); the published-name import below IS the
# registration trigger for orm/metrics.py.
from src.observability import ConfidenceMetricSnapshot as _ConfidenceMetricSnapshot  # noqa: E402, F401

__all__: list[str] = []
