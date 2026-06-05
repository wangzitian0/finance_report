"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import type {
    AnnualizedIncomeScheduleResponse,
    PersonalReportPackageContractResponse,
    PersonalReportPackageNotesResponse,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageTraceabilityResponse,
} from "@/lib/types";

function formatScheduleCurrency(value: number | string, currency: string): string {
    return formatCurrencyLocale(value, currency, "en-US", { maximumFractionDigits: 0 }).replace(/\u00a0/g, " ");
}

function renderAnchorDetail(primary: string, identifiers?: string[]) {
    return (
        <>
            <p className="mt-1 text-xs text-muted">{primary}</p>
            {identifiers?.length ? (
                <p className="mt-1 max-w-xs break-words font-mono text-[11px] text-muted">{identifiers.join(", ")}</p>
            ) : null}
        </>
    );
}

export default function PersonalReportPackagePage() {
    const [contract, setContract] = useState<PersonalReportPackageContractResponse | null>(null);
    const [readiness, setReadiness] = useState<PersonalReportPackageReadinessResponse | null>(null);
    const [annualizedSchedule, setAnnualizedSchedule] = useState<AnnualizedIncomeScheduleResponse | null>(null);
    const [packageNotes, setPackageNotes] = useState<PersonalReportPackageNotesResponse | null>(null);
    const [traceabilityAppendix, setTraceabilityAppendix] = useState<PersonalReportPackageTraceabilityResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let isMounted = true;

        Promise.all([
            apiFetch<PersonalReportPackageContractResponse>("/api/reports/package/contract"),
            apiFetch<PersonalReportPackageReadinessResponse>("/api/reports/package/readiness"),
            apiFetch<AnnualizedIncomeScheduleResponse>("/api/reports/package/annualized-income-schedule"),
            apiFetch<PersonalReportPackageNotesResponse>("/api/reports/package/notes"),
            apiFetch<PersonalReportPackageTraceabilityResponse>("/api/reports/package/traceability"),
        ])
            .then(([contractData, readinessData, scheduleData, notesData, traceabilityData]) => {
                if (!isMounted) return;
                setContract(contractData);
                setReadiness(readinessData);
                setAnnualizedSchedule(scheduleData);
                setPackageNotes(notesData);
                setTraceabilityAppendix(traceabilityData);
            })
            .catch((err) => {
                if (isMounted) setError(err instanceof Error ? err.message : "Failed to load package data.");
            });

        return () => {
            isMounted = false;
        };
    }, []);

    if (error) {
        return <div className="p-6 text-[var(--error)]">{error}</div>;
    }

    if (!contract || !readiness || !annualizedSchedule || !packageNotes || !traceabilityAppendix) {
        return <div className="p-6 text-muted">Loading package contract...</div>;
    }

    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Personal Report Package</h1>
                <p className="page-description">{contract.package_id}</p>
            </div>

            <section className="card p-5 mb-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                        <p className="text-xs font-mono text-muted">report_readiness</p>
                        <h2 className="font-semibold mt-1">Report Readiness</h2>
                        <p className="mt-2 text-sm text-muted">
                            {readiness.state === "blocked"
                                ? `${readiness.blocking_count} blocker${readiness.blocking_count === 1 ? "" : "s"} must be resolved before package output is trusted.`
                                : `Current package state is ${readiness.label.toLowerCase()}.`}
                        </p>
                    </div>
                    <Link className="badge badge-muted" href={readiness.action_href}>
                        {readiness.label}
                    </Link>
                </div>
                <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
                    <div>
                        <dt className="text-xs text-muted">Statements</dt>
                        <dd className="mt-1 font-semibold">{readiness.source_summary.statements ?? 0}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-muted">Journal Entries</dt>
                        <dd className="mt-1 font-semibold">{readiness.source_summary.posted_journal_entries ?? 0}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-muted">Manual Valuations</dt>
                        <dd className="mt-1 font-semibold">{readiness.source_summary.manual_valuations ?? 0}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-muted">Blockers</dt>
                        <dd className="mt-1 font-semibold">{readiness.blocking_count}</dd>
                    </div>
                </dl>
                {readiness.blockers.length ? (
                    <div className="mt-5 grid lg:grid-cols-2 gap-4">
                        {readiness.blockers.map((blocker) => (
                            <article key={blocker.code} className="border border-[var(--border)] rounded p-3">
                                <div className="flex items-start justify-between gap-3">
                                    <div>
                                        <p className="font-medium">{blocker.label}</p>
                                        <p className="text-xs font-mono text-muted mt-1">{blocker.code}</p>
                                    </div>
                                    <Link className="badge badge-muted" href={blocker.action_href}>
                                        {blocker.count}
                                    </Link>
                                </div>
                                <p className="mt-3 text-sm text-muted">{blocker.reason}</p>
                            </article>
                        ))}
                    </div>
                ) : null}
            </section>

            <div className="grid lg:grid-cols-2 gap-4 mb-6">
                {contract.sections.map((section) => (
                    <section key={section.section_id} className="card p-5">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <p className="text-xs font-mono text-muted">{section.section_id}</p>
                                <h2 className="font-semibold mt-1">{section.label}</h2>
                            </div>
                            <span className="badge badge-muted">{section.status}</span>
                        </div>
                        <dl className="mt-4 space-y-2 text-sm">
                            <div className="flex justify-between gap-3">
                                <dt className="text-muted">Owner</dt>
                                <dd className="font-medium">{section.owner_epic}</dd>
                            </div>
                            <div className="flex justify-between gap-3">
                                <dt className="text-muted">Endpoint</dt>
                                <dd className="font-mono text-xs text-right">{section.source_endpoint}</dd>
                            </div>
                            {section.blocking_issue ? (
                                <div className="flex justify-between gap-3">
                                    <dt className="text-muted">Follow-up</dt>
                                    <dd className="font-medium">{section.blocking_issue}</dd>
                                </div>
                            ) : null}
                        </dl>
                    </section>
                ))}
            </div>

            <section className="card p-5 mb-6">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p className="text-xs font-mono text-muted">{annualizedSchedule.section_id}</p>
                        <h2 className="font-semibold mt-1">Annualized Income Schedule</h2>
                    </div>
                    <span className="badge badge-muted">{annualizedSchedule.trailing_period_days} days</span>
                </div>
                <div className="mt-4 grid md:grid-cols-4 gap-3">
                    <div>
                        <p className="text-xs text-muted">Total</p>
                        <p className="mt-1 font-semibold">
                            {formatScheduleCurrency(annualizedSchedule.income.annualized_total, annualizedSchedule.income.currency)}
                        </p>
                    </div>
                    <div>
                        <p className="text-xs text-muted">Salary</p>
                        <p className="mt-1 font-semibold">
                            {formatScheduleCurrency(annualizedSchedule.income.annualized_salary, annualizedSchedule.income.currency)}
                        </p>
                    </div>
                    <div>
                        <p className="text-xs text-muted">Bonus</p>
                        <p className="mt-1 font-semibold">
                            {formatScheduleCurrency(annualizedSchedule.income.annualized_bonus, annualizedSchedule.income.currency)}
                        </p>
                    </div>
                    <div>
                        <p className="text-xs text-muted">Dividend</p>
                        <p className="mt-1 font-semibold">
                            {formatScheduleCurrency(annualizedSchedule.income.annualized_dividend, annualizedSchedule.income.currency)}
                        </p>
                    </div>
                </div>
                <div className="mt-5 grid lg:grid-cols-2 gap-4">
                    <div>
                        <h3 className="text-sm font-semibold">Restricted Holdings</h3>
                        <div className="mt-3 space-y-2">
                            {annualizedSchedule.restricted_holdings.map((holding) => (
                                <div key={`${holding.compensation_type}:${holding.ticker}`} className="border border-[var(--border)] rounded p-3">
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <p className="font-medium">{holding.ticker}</p>
                                            <p className="text-xs text-muted">{holding.compensation_type}</p>
                                        </div>
                                        <p className="font-semibold">
                                            {formatScheduleCurrency(holding.fair_value, holding.currency)}
                                        </p>
                                    </div>
                                    <dl className="mt-3 space-y-1 text-xs">
                                        {holding.vesting_schedule ? (
                                            <div className="flex justify-between gap-3">
                                                <dt className="text-muted">Vesting</dt>
                                                <dd>{holding.vesting_schedule}</dd>
                                            </div>
                                        ) : null}
                                        {holding.unlock_date ? (
                                            <div className="flex justify-between gap-3">
                                                <dt className="text-muted">Unlock</dt>
                                                <dd>{holding.unlock_date}</dd>
                                            </div>
                                        ) : null}
                                    </dl>
                                </div>
                            ))}
                        </div>
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold">Net Worth Treatment</h3>
                        <dl className="mt-3 space-y-2 text-sm">
                            <div className="flex justify-between gap-3">
                                <dt className="text-muted">Liquid Default</dt>
                                <dd className="font-mono text-xs text-right">
                                    {annualizedSchedule.net_worth_treatment.liquid_net_worth_default}
                                </dd>
                            </div>
                            <div className="flex justify-between gap-3">
                                <dt className="text-muted">Restricted Basis</dt>
                                <dd className="font-mono text-xs text-right">
                                    {annualizedSchedule.net_worth_treatment.restricted_wealth_basis}
                                </dd>
                            </div>
                        </dl>
                        <ul className="mt-4 space-y-1 text-sm text-muted">
                            {annualizedSchedule.notes.map((note) => (
                                <li key={note}>{note}</li>
                            ))}
                        </ul>
                    </div>
                </div>
            </section>

            <section className="card p-5 mb-6">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p className="text-xs font-mono text-muted">{packageNotes.section_id}</p>
                        <h2 className="font-semibold mt-1">{packageNotes.label}</h2>
                    </div>
                    <span className="badge badge-muted">{packageNotes.status}</span>
                </div>
                <p className="mt-4 text-sm text-muted">{packageNotes.non_compliance_statement}</p>
                <div className="mt-5 grid lg:grid-cols-2 gap-4">
                    {packageNotes.notes.map((note) => (
                        <article key={note.note_id} className="border border-[var(--border)] rounded p-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="font-medium">{note.label}</p>
                                    <p className="text-xs font-mono text-muted mt-1">{note.note_id}</p>
                                </div>
                                <span className="badge badge-muted">{note.owner_epic}</span>
                            </div>
                            <p className="mt-3 text-sm text-muted">{note.disclosure}</p>
                            <dl className="mt-3 space-y-1 text-xs">
                                <div className="flex justify-between gap-3">
                                    <dt className="text-muted">Basis</dt>
                                    <dd className="font-mono text-right">{note.basis}</dd>
                                </div>
                                <div className="flex justify-between gap-3">
                                    <dt className="text-muted">Source</dt>
                                    <dd className="font-mono text-right">{note.source_state}</dd>
                                </div>
                            </dl>
                        </article>
                    ))}
                </div>
            </section>

            <section className="card p-5 mb-6">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p className="text-xs font-mono text-muted">{traceabilityAppendix.section_id}</p>
                        <h2 className="font-semibold mt-1">{traceabilityAppendix.label}</h2>
                    </div>
                    <span className="badge badge-muted">{traceabilityAppendix.status}</span>
                </div>
                <div className="mt-5 overflow-x-auto">
                    <table className="min-w-full text-sm">
                        <thead className="text-left text-xs text-muted">
                            <tr>
                                <th className="py-2 pr-4 font-medium">Line</th>
                                <th className="py-2 pr-4 font-medium">Source</th>
                                <th className="py-2 pr-4 font-medium">Ledger</th>
                                <th className="py-2 pr-4 font-medium">Review</th>
                                <th className="py-2 font-medium">Confidence</th>
                            </tr>
                        </thead>
                        <tbody>
                            {traceabilityAppendix.lines.map((line) => (
                                <tr key={line.line_id} className="border-t border-[var(--border)] align-top">
                                    <td className="py-3 pr-4">
                                        <p className="font-mono text-xs">{line.line_id}</p>
                                        <p className="mt-1 text-xs text-muted">{line.label}</p>
                                    </td>
                                    <td className="py-3 pr-4">
                                        <p className="font-mono text-xs">{line.source_state}</p>
                                        {renderAnchorDetail(
                                            (line.source_anchor.source_types ?? []).join(", ") || line.source_anchor.state,
                                            line.source_anchor.identifiers,
                                        )}
                                    </td>
                                    <td className="py-3 pr-4">
                                        <p className="font-mono text-xs">{line.ledger_anchor.state}</p>
                                        {renderAnchorDetail(
                                            (line.ledger_anchor.entry_statuses ?? []).join(", ") || line.ledger_anchor.unavailable_reason || line.ledger_anchor.state,
                                            line.ledger_anchor.identifiers,
                                        )}
                                    </td>
                                    <td className="py-3 pr-4 font-mono text-xs">{line.review_state}</td>
                                    <td className="py-3">
                                        <span className="badge badge-muted">{line.confidence_tier}</span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <div className="mt-5 grid lg:grid-cols-2 gap-4">
                    {traceabilityAppendix.completeness_warnings.map((warning) => (
                        <article key={warning.code} className="border border-[var(--border)] rounded p-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="font-medium">{warning.label}</p>
                                    <p className="text-xs font-mono text-muted mt-1">{warning.code}</p>
                                </div>
                                <span className="badge badge-muted">{warning.state}</span>
                            </div>
                            {warning.remediation ? (
                                <p className="mt-3 text-sm text-muted">{warning.remediation}</p>
                            ) : null}
                        </article>
                    ))}
                </div>
            </section>

            <section className="card p-5">
                <h2 className="font-semibold">Export Contract</h2>
                <dl className="mt-4 space-y-2 text-sm">
                    <div className="flex justify-between gap-3">
                        <dt className="text-muted">Formats</dt>
                        <dd className="font-medium">{contract.export_contract.formats.join(", ")}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                        <dt className="text-muted">CSV Columns</dt>
                        <dd className="font-mono text-xs text-right">{contract.export_contract.csv_columns.join(", ")}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                        <dt className="text-muted">Decimal Serialization</dt>
                        <dd className="font-medium">{contract.period_semantics.decimal_serialization}</dd>
                    </div>
                </dl>
            </section>
        </div>
    );
}
