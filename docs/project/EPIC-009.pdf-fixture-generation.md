# EPIC-009: PDF Fixture Generation for Testing

> **Status ownership**: This EPIC owns AC9.x scope only. Tool usage,
> template policy, generated-output policy, font fallback, and live proof are
> owned by [PDF Fixtures SSOT](../ssot/pdf-fixtures.md), code, and tests.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Dependencies**: EPIC-003, EPIC-008

## Objective

Create offline tooling that generates synthetic bank and brokerage PDF
statements for deterministic parsing, reconciliation, reporting, and E2E
tests. Fixtures use fictional data; real PDFs stay local and gitignored.

## Ownership

| Fact | Owner |
|---|---|
| Commands, local-only input/output policy, template format, and font fallback | [PDF Fixtures SSOT](../ssot/pdf-fixtures.md) |
| Analyzer and template extraction behavior | `tools/_lib/pdf_fixtures/analyzers/`, `tools/analyze_pdf_fixture.py` |
| Generator, validator, and fake-data behavior | `tools/_lib/pdf_fixtures/`, `tools/generate_pdf_fixtures.py` |
| Parseability, date-format, balance, and template contracts | `tests/tooling/test_pdf_fixture_*.py` |
| Real PDF exclusion and sensitive-output policy | `.gitignore`, `tools/_lib/pdf_fixtures/.gitignore`, tests |

## Acceptance Criteria

> Keep this section as AC definitions only. Proof mappings are owned by tests
> and generated traceability reports.

### AC9.1: PDF Format Analysis

| ID | Requirement |
|---|---|
| AC9.1.1 | PDF analyzer exists |
| AC9.1.2 | Template extractor exists |
| AC9.1.3 | CLI tool exists |
| AC9.1.4 | DBS template exists |
| AC9.1.5 | CMB template exists |
| AC9.1.6 | Mari Bank template exists |

### AC9.2: PDF Generators

| ID | Requirement |
|---|---|
| AC9.2.1 | Base generator class exists |
| AC9.2.2 | DBS generator exists |
| AC9.2.3 | CMB generator exists |
| AC9.2.4 | Mari Bank generator exists |
| AC9.2.5 | Font utilities exist |
| AC9.2.6 | Fake data generator exists |
| AC9.2.7 | Main script exists |

### AC9.3: PDF Validation

| ID | Requirement |
|---|---|
| AC9.3.1 | Format validator exists |
| AC9.3.2 | Generated DBS PDF parseable |
| AC9.3.3 | Generated CMB PDF parseable |
| AC9.3.4 | Generated Mari PDF parseable |
| AC9.3.5 | Balance calculations correct |
| AC9.3.6 | Date formats correct |

### AC9.4: Documentation And Integration

| ID | Requirement |
|---|---|
| AC9.4.1 | Format analysis README |
| AC9.4.2 | Generation README |
| AC9.4.3 | Template format specification |
| AC9.4.4 | Usage examples |

### AC9.5: Git Configuration

| ID | Requirement |
|---|---|
| AC9.5.1 | .gitignore excludes real PDFs |
| AC9.5.2 | Format templates committed |
| AC9.5.3 | Generators committed |
| AC9.5.4 | Analyzers committed |
| AC9.5.5 | Validators committed |

### AC9.6: Generator Implementation Quality

| ID | Requirement |
|---|---|
| AC9.6.1 | DBS generator loads template |
| AC9.6.2 | CMB generator loads template |
| AC9.6.3 | CMB generator supports Chinese fonts |
| AC9.6.4 | Mari generator generates interest section |
| AC9.6.5 | Generators use fictional data |

### AC9.7: CLI And Script Functionality

| ID | Requirement |
|---|---|
| AC9.7.1 | Main script supports --source parameter |
| AC9.7.2 | Main script supports --output parameter |
| AC9.7.3 | Analyzer CLI supports input/output |

## Related

- [PDF Fixtures SSOT](../ssot/pdf-fixtures.md)
- [EPIC-003: Statement Parsing](./EPIC-003.statement-parsing.md)
- [EPIC-008: Testing Strategy](./EPIC-008.testing-strategy.md)
