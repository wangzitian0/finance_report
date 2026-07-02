# EPIC-009: PDF Fixture Generation for Testing

> **Status ownership**: This EPIC owns AC9.x scope only. Tool usage,
> template policy, generated-output policy, font fallback, and live proof are
> owned by [`testing` package §PDF Fixtures](../../common/testing/README.md#pdf-fixtures), code, and tests.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Dependencies**: EPIC-003, EPIC-008

## Objective

Create offline tooling that generates synthetic bank and brokerage PDF
statements for deterministic parsing, reconciliation, reporting, and E2E
tests. Fixtures use fictional data; real PDFs stay local and gitignored.

## Ownership

| Fact | Owner |
|---|---|
| Commands, local-only input/output policy, template format, and font fallback | [`testing` package §PDF Fixtures](../../common/testing/README.md#pdf-fixtures) |
| Analyzer and template extraction behavior | `common/testing/fixtures/pdf/analyzers/`, `tools/analyze_pdf_fixture.py` |
| Generator, validator, and fake-data behavior | `common/testing/fixtures/pdf/`, `tools/generate_pdf_fixtures.py` |
| Parseability, date-format, balance, and template contracts | `tests/tooling/test_pdf_fixture_*.py` |
| Real PDF exclusion and sensitive-output policy | `.gitignore`, `common/testing/fixtures/pdf/.gitignore`, tests |

## Acceptance Criteria

> **This EPIC's AC9.1–AC9.8 groups are NO LONGER defined here.** They migrated
> into the `testing` package and are owned by, and sourced directly from,
> [`common/testing/contract.py`](../../common/testing/contract.py)'s
> `roadmap` under the package-scoped `AC-testing.<group>.<seq>` id scheme (the
> leading "9" is dropped and the group/seq preserved, so `AC9.<g>.<s>` becomes
> `AC-testing.<g>.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source, per the `counter`/`audit` precedent
> ([EPIC-025](./EPIC-025.dry-ssot-simplification.md)).
>
> Migrated ids (each was the same-suffix `AC9.<g>.<s>`, "9" dropped):
> PDF format analysis — `AC-testing.1.1`, `AC-testing.1.2`, `AC-testing.1.3`,
> `AC-testing.1.4`, `AC-testing.1.5`, `AC-testing.1.6`; PDF generators —
> `AC-testing.2.1`, `AC-testing.2.2`, `AC-testing.2.3`, `AC-testing.2.4`,
> `AC-testing.2.5`, `AC-testing.2.6`, `AC-testing.2.7`; PDF validation —
> `AC-testing.3.1`, `AC-testing.3.2`, `AC-testing.3.3`, `AC-testing.3.4`,
> `AC-testing.3.5`, `AC-testing.3.6`; documentation — `AC-testing.4.1`,
> `AC-testing.4.2`, `AC-testing.4.3`, `AC-testing.4.4`; git configuration —
> `AC-testing.5.1`, `AC-testing.5.2`, `AC-testing.5.3`, `AC-testing.5.4`,
> `AC-testing.5.5`; generator implementation quality — `AC-testing.6.1`,
> `AC-testing.6.2`, `AC-testing.6.3`, `AC-testing.6.4`, `AC-testing.6.5`; CLI
> and script functionality — `AC-testing.7.1`, `AC-testing.7.2`,
> `AC-testing.7.3`; real-format parity contracts — `AC-testing.8.1`,
> `AC-testing.8.2`, `AC-testing.8.3`.

## Related

- [`testing` package §PDF Fixtures](../../common/testing/README.md#pdf-fixtures)
- [EPIC-003: Statement Parsing](./EPIC-003.statement-parsing.md)
- [EPIC-008: Testing Strategy](./EPIC-008.testing-strategy.md)
