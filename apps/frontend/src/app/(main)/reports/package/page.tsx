"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import type { PersonalReportPackageContractResponse } from "@/lib/types";

export default function PersonalReportPackagePage() {
    const [contract, setContract] = useState<PersonalReportPackageContractResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let isMounted = true;

        apiFetch<PersonalReportPackageContractResponse>("/api/reports/package/contract")
            .then((data) => {
                if (isMounted) setContract(data);
            })
            .catch((err) => {
                if (isMounted) setError(err instanceof Error ? err.message : "Failed to load package contract.");
            });

        return () => {
            isMounted = false;
        };
    }, []);

    if (error) {
        return <div className="p-6 text-[var(--error)]">{error}</div>;
    }

    if (!contract) {
        return <div className="p-6 text-muted">Loading package contract...</div>;
    }

    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Personal Report Package</h1>
                <p className="page-description">{contract.package_id}</p>
            </div>

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
