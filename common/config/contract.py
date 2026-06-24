"""The ``config`` package's machine-checkable :class:`PackageContract`.

``config`` is internal tooling — env-key + schema-validation helpers
(``env_keys``, ``schema_validation``) — not a domain bounded context, so it
publishes no curated symbol language (``interface=[]``); callers import its
modules directly. The contract governs it as a ``kernel`` leaf (``depends_on=[]``)
with an invariant pinned to its test. (The DAG import-scan only inspects
``src.<pkg>`` imports, so for a ``common/``-implemented package leaf-purity is a
declared, not a scanned, property.)
A curated published-language surface is a future cleanup.
"""

from __future__ import annotations

from common.governance.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="config",
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles=["env_keys", "schema_validation"],
    implementations={"be": "common/config", "fe": None},
    interface=[],
    events=[],
    invariants=[
        Invariant(
            id="env-key-extraction-robust",
            statement="Parsing env keys from a missing source file yields an empty set, not an error, so the consistency check degrades gracefully.",
            test="tests/tooling/test_check_env_keys.py::test_returns_empty_set_for_missing_file",
        ),
    ],
    roadmap=[],
)
