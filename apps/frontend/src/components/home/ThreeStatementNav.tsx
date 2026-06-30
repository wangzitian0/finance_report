"use client";

import Link from "next/link";

// EPIC-022 AC22.21.6: the three financial statements are the product. Home leads
// with a compact segmented entry into each, deep-linking to the full report.
const STATEMENTS = [
    { label: "Balance Sheet", href: "/reports/balance-sheet", hint: "What you own and owe" },
    { label: "Income", href: "/reports/income-statement", hint: "Money in and out" },
    { label: "Cash Flow", href: "/reports/cash-flow", hint: "Where cash moved" },
];

export function ThreeStatementNav() {
    return (
        <nav aria-label="Financial statements" className="grid grid-cols-3 gap-2">
            {STATEMENTS.map((s) => (
                <Link
                    key={s.href}
                    href={s.href}
                    className="card p-3 text-center transition-colors hover:bg-[var(--background-muted)]"
                >
                    <span className="block text-sm font-medium">{s.label}</span>
                    <span className="mt-0.5 block text-xs text-muted">{s.hint}</span>
                </Link>
            ))}
        </nav>
    );
}
