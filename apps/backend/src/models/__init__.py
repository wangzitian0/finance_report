"""SQLAlchemy models package.

This package is intentionally **not** a re-export hub (issue #1461,
AC-meta.facade.*). Import each model from its owning module, e.g.
``from src.models.journal import JournalEntry`` — never ``from src.models
import JournalEntry``. The hub form is forbidden by
``tests/tooling/test_no_models_facade.py``.

For the eager "import all models so they register on ``Base.metadata``"
discovery side effect (Alembic autogenerate, test schema build, app startup),
import :mod:`src.models._registry` instead.
"""
