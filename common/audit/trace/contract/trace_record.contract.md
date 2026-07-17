# TraceRecord Contract v1

## Purpose

`TraceRecord` is the language-neutral, append-only assurance record. It has two
semantic types only: `observation` for an executed measurement and `decision`
for a policy fold over exact parent records.

## Closed fields

The v1 wire object contains exactly: `schema_version`, `record_type`, typed
`scope`, versioned `target`, `target_class`, versioned `assertion`, `authority`,
`result`, `execution_id`, nullable `causality`, `evidence_manifest_digest`,
`occurred_at`, `parent_ids`, `supersedes_id`, string-encoded `score`,
`reason_code`, `content_digest`, and `record_id`. Unknown or missing fields are
invalid. There is no generic payload or metadata map.

Scope, target, assertion, execution, version, provenance, and reason identifiers
are opaque technical identifiers supplied by package composition adapters. They
must never contain raw user identity, document text, prompts, account labels, or
financial values. This keeps canonical digests verifiable in anonymized database
snapshots without copying sensitive payloads into the assurance graph.

The authority snapshot contains `package`, the existing package `tier`, a
matrix-valid `proof_kind`, `provenance`, `execution_stage`,
`assertion_owner_digest`, and `producer_version`. Manual adjudication retains
the producing package's existing four-tier authority and a matrix-valid proof
kind; it uses `provenance=manual` and `execution_stage=manual.adjudication` and
never creates a fifth or undecided tier.

## Canonical identity

Canonical JSON is UTF-8, ASCII-escaped, key-sorted, and compact. Decimal scores
use the audit `Ratio` language and serialize as normalized strings. Timestamps
normalize to UTC before encoding. The SHA-256 of the semantic payload is
`content_digest`; UUID5 over that digest is `record_id`. Equivalent records are
therefore content-idempotent across DB, JSONL, and JUnit adapters.

The public JSON codec restores observations only. A decision cannot be trusted
from a self-contained wire envelope because its policy and parent graph are not
inside that envelope; decision restore is therefore exclusive to the SQL
repository, which reconstructs typed columns and replays the registered policy
over every parent before returning the record.

## Causality

An observation has no parents or causality mode. A decision requires unique
current parent heads from the same typed scope and a registered versioned policy.
`DIRECT` requires the same target version and execution. `MANIFEST` may use
cross-target/cross-execution parents only when the policy validates the complete
exact parent set. Missing, stale, skipped, errored, unproven, cross-scope, or
policy-incomplete parents are invalid. The graph is acyclic and the persisted
parent count seals the exact edge set. An authoritative decision consumes only
passed/authoritative parents; a rejected decision may consume a failed
observation so rejection stays causal and queryable.

An LLM-produced financial observation becomes authoritative only when the final
decision is CODE-ONLY and includes an authoritative CODE-ONLY invariant or
promotion decision parent over the same exact target. DIRECT additionally makes
every parent share the final decision's execution.

## Persistence

Records and normalized parent links are insert-only. Correction appends a new
record with `supersedes_id` naming the prior current head; no prior row changes.
Repository, ORM, and PostgreSQL constraints all enforce typed scope,
idempotency, sealed acyclic parent graphs, append-only mutation, and fail-closed
persistence.
The storage row seals the expected parent count, and a deferred database trigger
requires the normalized link set to match it. A later link insert therefore
cannot rewrite the causal meaning of an already-digested decision.

The SQL repository flushes into a caller-owned unit of work; it does not commit
independently. A package use case must commit its authoritative side effect and
the complete TraceRecord causal set in the same transaction, and roll back both
when any append fails.

Supersession is scoped to a `TraceLineage`: stable target kind/id plus stable
assertion kind/id. Versions remain exact record pins and may advance in a
superseding record. Independent observations may coexist across executions; only
authoritative decision heads are singleton. Fixed confidence cohorts enumerate
stable lineages and fail closed on ambiguous unsuperseded measurements.
