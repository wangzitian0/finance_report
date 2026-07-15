# `common/` — the package review surface

`common/` is where the repo's **packages** live as specs and high-level review
surfaces. A package is a DDD bounded context; each one is a directory
`common/<pkg>/` holding its `readme.md` (ubiquitous language), `contract.py` (a
machine-checkable `PackageContract`), and `todo.md` (its worklist).

## Map

Contract-carrying packages, by layer:

- **L0 meta** — [`meta/`](../meta/readme.md): The ``meta`` package's own :class:`PackageContract`.
- **L1 infra** — [`audit/`](../audit/readme.md): The ``audit`` package's machine-checkable :class:`PackageContract`., [`llm/`](../llm/readme.md): The ``llm`` package's machine-checkable :class:`PackageContract`., [`observability/`](../observability/readme.md): The ``observability`` package's machine-checkable :class:`PackageContract`., [`platform/`](../platform/readme.md): The ``platform`` package's machine-checkable :class:`PackageContract`., [`runtime/`](../runtime/readme.md): The ``runtime`` package's machine-checkable :class:`PackageContract`., [`testing/`](../testing/readme.md): The ``testing`` package's machine-checkable :class:`PackageContract`.
- **L2 middleware** — [`counter/`](../counter/readme.md): The ``counter`` package's machine-checkable :class:`PackageContract`.
- **L3 domain** — [`advisor/`](../advisor/readme.md): The ``advisor`` package's machine-checkable :class:`PackageContract`., [`extraction/`](../extraction/readme.md): The ``extraction`` package's machine-checkable :class:`PackageContract`., [`identity/`](../identity/readme.md): The ``identity`` package's machine-checkable :class:`PackageContract`., [`ledger/`](../ledger/readme.md): The ``ledger`` package's machine-checkable :class:`PackageContract`., [`portfolio/`](../portfolio/readme.md): The ``portfolio`` package's machine-checkable :class:`PackageContract`., [`pricing/`](../pricing/readme.md): The ``pricing`` package's machine-checkable :class:`PackageContract`., [`reconciliation/`](../reconciliation/readme.md): The ``reconciliation`` package's machine-checkable :class:`PackageContract`., [`reporting/`](../reporting/readme.md): The ``reporting`` package's machine-checkable :class:`PackageContract`.
- **L4 app** — [`ui_core/`](../ui_core/readme.md): ui_core
