"""PackageContract for ``counter``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="counter",
    status="active",
    tier="CODE-ONLY",
    depends_on="platform".split(),
    roles="base extension".split(),
    implementations={"be": "apps/backend/src/counter", "fe": None},
    context=ContextScope(
        purpose="Own reusable per-user and global named-event tallies, with a narrow counter value language and one counter-owned increment event.",
        in_scope=[
            "CounterKey and non-negative Count vocabulary.",
            "Per-user and global tally operations and repository port.",
            "Emission of the counter.Incremented event after a counter mutation.",
        ],
        out_of_scope=[
            "Business-domain metrics, reporting interpretation, or product analytics.",
            "Generic event-bus or outbox persistence ownership.",
            "Workflow, application routing, or cross-domain orchestration.",
        ],
    ),
    relationships=rels(
        "counter",
        """
platform|consumer-port|Consumes the platform EventBus/outbox port to publish the counter-owned Incremented event atomically.
""",
    ),
    units=units(
        """
CounterKey|vo|base/types/key.py
Count|vo|base/types/count.py
Incremented|ev|base/types/events.py
CounterRepository|repo|base/repository.py|extension/sql.py
"""
    ),
    interface="""
Count CounterError CounterKey CounterRepository Incremented InvalidCounterKeyError
NegativeCountError get_count increment read_count record_increment
""".split(),
    events=["Incremented"],
    invariants=invs(
        """
key-valid|A CounterKey must be a non-empty lowercase dotted 'domain.action' identifier.|$be/counter/test_key.py::test_counter_key_rejects_invalid
count-non-negative|A Count is a non-negative tally.|$be/counter/test_count.py::test_count_rejects_negative
@$t/test_counter_package.py
converges-by-layer|The package converges into base/ (pure core) + extension/ (edges).|test_AC_counter_1_1_counter_converges_by_layer
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_counter_1_1_only_all_is_the_published_language
base-layer-pure|The base/ layer never imports the package's own extension/ or the ORM.|test_AC_counter_1_2_base_layer_is_pure
passes-own-governance-gate|Check_package_contract validates counter with no violations.|test_AC_counter_1_4_package_contract_gate_passes_for_counter
@-
async-repository-composition|CounterRepository is async, SqlCounterRepository structurally satisfies it.|$t/test_s3_pr_d_structure.py::test_AC_counter_repository_5_async_adapter_and_api_composition
"""
    ),
    roadmap=acs(
        "counter",
        """
@$be/counter/test_key.py
1.1||test_counter_key_rejects_invalid
@$be/counter/test_count.py
1.2||test_count_rejects_negative
@$be/counter/test_increment.py|P1
1.3||test_increment_is_per_user
@$be/counter/test_query.py|P1
1.4||test_global_vs_per_user_count
@$t/test_s3_pr_d_structure.py
repository.5||test_AC_counter_repository_5_async_adapter_and_api_composition
""",
    ),
)
