"""Eager model discovery — import every model module for its registration side effect.

Importing a model module runs its class definitions, which register the mapped
classes on ``src.database.Base.metadata``. SQLAlchemy needs *all* models loaded
before ``Base.metadata.create_all`` (test schema build) or Alembic autogenerate
can see the full schema, and before cross-module string relationships can be
configured.

This module replaces the former implicit discovery side effect of importing the
``src.models`` re-export hub (issue #1461, AC-meta.facade.*). The hub is now
empty; discovery sites import this module explicitly instead:

* ``migrations/env.py``      — Alembic autogenerate target metadata
* ``tests/conftest.py``      — per-worker ``create_all`` schema build
* ``src/main.py``            — eager mapper registration at app startup
* ``common/meta/extension/generate_db_schema_reference.py`` — schema reference generation

This is NOT a re-export facade: it publishes no symbols (``__all__`` is empty).
Other code must import each model from its owning module
(``from src.models.layer2 import AtomicTransaction``), never from here or the hub.
"""

from __future__ import annotations

# Packages that own their ORM (moved from here, #1675) register the mappers in
# their root __init__; importing the published root is the whole side effect.
import src.advisor  # noqa: F401,E402
import src.extraction  # noqa: F401,E402

# The identity package (User/AiFeedback) registers its ORM models onto
# Base.metadata via its SQL adapter module, mirroring counter/platform (whose
# tables are registered the same way, not from this models package).
import src.identity.extension.sql  # noqa: F401,E402
import src.ledger  # noqa: F401,E402
import src.llm  # noqa: F401,E402
import src.platform  # noqa: F401,E402
import src.portfolio  # noqa: F401,E402
import src.pricing  # noqa: F401,E402
import src.reconciliation  # noqa: F401,E402

# observability publishes its one ORM class lazily (importing its root must
# stay light for logging consumers); the published-name import below IS the
# registration trigger for orm/metrics.py.
from src.observability import ConfidenceMetricSnapshot as _ConfidenceMetricSnapshot  # noqa: E402, F401

# Imported purely for the metadata-registration side effect; ordering is
# irrelevant because SQLAlchemy resolves relationships after all are loaded.
from . import (  # noqa: F401
    correction,
    evidence,
    layer2,
    layer3,
    layer4,
    statement_enums,
    statement_summary,
)

__all__: list[str] = []
