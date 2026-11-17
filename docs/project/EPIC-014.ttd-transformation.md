# EPIC-014: Test-Driven Documentation (TTD) Transformation

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1719): TTD philosophy and SSOT HLS design doc. -->

> **Status**: Design Doc
> **Vision Anchor**: `decision-filter-accuracy-auditability`

Docs explain **why** and **how**; executable tests and CI checks enforce **what is mandatory**. Authoritative package metadata lives in `common/<pkg>/contract.py` and [common/meta/data/MANIFEST.yaml](../../common/meta/data/MANIFEST.yaml).

## HLS Families (`MANIFEST.yaml`)

- **concept vs clause**: A `concept` is an independently governed SSOT owner; a `clause`/`matrix`/`registry`/`baseline` parameterizes a parent concept.
- **FR families (7)**: `accounting`, `reporting`, `extraction`, `schema`, `platform`, `identity`, `governance`.
- **Target shape**: `common/<pkg>/readme.md` -> generated MkDocs references (`docs/reference/`) -> code/CI gates.

## Owned Surfaces

- [AGENTS.md](https://github.com/wangzitian0/finance_report/blob/main/AGENTS.md) · [AUDITS.md](./AUDITS.md) · [tdd.md](../../common/testing/tdd.md) · [orchestration.md](../agents/orchestration.md) · [red-lines.md](../agents/red-lines.md) · [branch-policy.md](../contributing/branch-policy.md)
