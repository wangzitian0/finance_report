import Link from "next/link";

const reports = [
    { id: "balance-sheet", title: "Balance Sheet", description: "Assets, liabilities, and equity at a point in time", icon: "📊", href: "/reports/balance-sheet", available: true },
    { id: "income-statement", title: "Income Statement", description: "Revenue and expenses over a period", icon: "📈", href: "/reports/income-statement", available: true },
    { id: "cash-flow", title: "Cash Flow Statement", description: "Cash movements by operating, investing, and financing activities", icon: "💰", href: "/reports/cash-flow", available: false },
];

export default function ReportsPage() {
    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Reports</h1>
                <p className="page-description">Generate and view financial reports following standard accounting principles.</p>
            </div>

            <div className="grid md:grid-cols-3 gap-4 mb-6">
                {reports.map((report) => (
                    <ReportCard key={report.id} report={report} />
                ))}
            </div>

            <div className="card p-5">
                <h2 className="font-semibold mb-3">Accounting Equation</h2>
                <div className="flex items-center justify-center gap-3 text-lg flex-wrap">
                    <span className="px-3 py-1.5 rounded-md bg-[var(--success-muted)] text-[var(--success)] font-mono">Assets</span>
                    <span className="text-muted">=</span>
                    <span className="px-3 py-1.5 rounded-md bg-[var(--error-muted)] text-[var(--error)] font-mono">Liabilities</span>
                    <span className="text-muted">+</span>
                    <span className="px-3 py-1.5 rounded-md bg-[var(--info-muted)] text-[var(--info)] font-mono">Equity</span>
                </div>
                <p className="text-center text-xs text-muted mt-3">All financial reports maintain this fundamental balance</p>
            </div>
        </div>
    );
}

interface ReportCardProps {
    report: { id: string; title: string; description: string; icon: string; href: string; available: boolean };
}

function ReportCard({ report }: ReportCardProps) {
    const content = (
        <div className={`card p-5 transition-colors ${report.available ? "hover:border-[var(--accent)]" : "opacity-60"}`}>
            <div className="flex items-start justify-between mb-3">
                <span className="text-3xl">{report.icon}</span>
                {!report.available && <span className="badge badge-muted">Coming Soon</span>}
            </div>
            <h3 className="font-semibold text-[var(--accent)] mb-1">{report.title}</h3>
            <p className="text-sm text-muted">{report.description}</p>
            {report.available && (
                <div className="mt-3 flex items-center text-xs text-muted">
                    <span>View report</span>
                    <svg className="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                </div>
            )}
        </div>
    );

    return report.available ? <Link href={report.href}>{content}</Link> : content;
}
