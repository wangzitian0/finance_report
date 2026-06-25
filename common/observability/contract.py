"""The ``observability`` package's machine-checkable :class:`PackageContract`.

``observability`` is internal tooling — the OpenPanel query CLI
(``openpanel_query``) — not a domain bounded context, so it publishes no curated
symbol language (``interface=[]``); callers invoke its module/CLI directly.
The contract still governs it: a ``kernel`` leaf (`depends_on=[]`) with an invariant pinned to its test. A curated published-language
surface is a future cleanup.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="observability",
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles=["openpanel_query"],
    implementations={"be": "common/observability", "fe": None},
    interface=[],
    events=[],
    invariants=[
        Invariant(
            id="api-key-from-env-not-argv",
            statement="The OpenPanel query CLI reads its API key from the environment, never from command-line args (no secret in argv).",
            test="tests/tooling/test_openpanel_query.py::test_AC23_1_4_api_key_read_from_env_not_args",
        ),
    ],
    roadmap=[],
)
