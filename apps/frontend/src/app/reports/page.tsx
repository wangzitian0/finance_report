import Link from "next/link";

const reports: {
    id: string;
    title: string;
    description: string;
    icon: string;
    href: string;
    available: boolean;
    color: "emerald" | "amber" | "cyan";
}[] = [
    {
        id: "balance-sheet",
        title: "Balance Sheet",
        description: "Assets, liabilities, and equity at a point in time",
        icon: "📊",
        href: "/reports/balance-sheet",
        available: true,
        color: "emerald",
    },
    {
        id: "income-statement",
        title: "Income Statement",
        description: "Revenue and expenses over a period",
        icon: "📈",
        href: "/reports/income-statement",
        available: true,
        color: "amber",
    },
    {
        id: "cash-flow",
        title: "Cash Flow Statement",
        description: "Cash movements by operating, investing, and financing activities",
        icon: "💰",
        href: "/reports/cash-flow",
        available: false,
        color: "cyan",
    },
];

export default function ReportsPage() {
    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-8">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="mb-10">
                    <p className="text-xs uppercase tracking-[0.3em] text-emerald-500 mb-2">
                        Financial Statements
                    </p>
                    <h1 className="text-4xl font-semibold text-white">Reports</h1>
                    <p className="mt-2 text-slate-400 max-w-2xl">
                        Generate and view financial reports. All reports follow standard
                        accounting principles and the accounting equation.
                    </p>
                </div>

                {/* Report Cards */}
                <div className="grid md:grid-cols-3 gap-6">
                    {reports.map((report) => (
                        <ReportCard key={report.id} report={report} />
                    ))}
                </div>

                {/* Accounting Equation Reminder */}
                <div className="mt-12 rounded-2xl border border-slate-700/50 bg-slate-800/30 p-6">
                    <h2 className="text-lg font-medium text-white mb-3">
                        Accounting Equation
                    </h2>
                    <div className="flex items-center justify-center gap-4 text-lg">
                        <span className="px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 font-mono">
                            Assets
                        </span>
                        <span className="text-slate-500">=</span>
                        <span className="px-4 py-2 rounded-lg bg-rose-500/10 text-rose-400 font-mono">
                            Liabilities
                        </span>
                        <span className="text-slate-500">+</span>
                        <span className="px-4 py-2 rounded-lg bg-blue-500/10 text-blue-400 font-mono">
                            Equity
                        </span>
                    </div>
                    <p className="text-center text-sm text-slate-500 mt-4">
                        All financial reports maintain this fundamental balance
                    </p>
                </div>
            </div>
        </div>
    );
}

interface ReportCardProps {
    report: {
        id: string;
        title: string;
        description: string;
        icon: string;
        href: string;
        available: boolean;
        color: "emerald" | "amber" | "cyan";
    };
}

const colorClasses = {
    emerald: "border-emerald-500/30 hover:border-emerald-500/50 hover:shadow-emerald-500/5",
    amber: "border-amber-500/30 hover:border-amber-500/50 hover:shadow-amber-500/5",
    cyan: "border-cyan-500/30 hover:border-cyan-500/50 hover:shadow-cyan-500/5",
};

const accentClasses = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    cyan: "text-cyan-400",
};

function ReportCard({ report }: ReportCardProps) {
    const content = (
        <div
            className={`
        rounded-2xl border bg-slate-800/30 p-6
        transition-all duration-300 hover:shadow-xl
        ${colorClasses[report.color]}
        ${!report.available ? "opacity-60" : ""}
      `}
        >
            <div className="flex items-start justify-between mb-4">
                <span className="text-4xl" role="img" aria-label={report.title}>
                    {report.icon}
                </span>
                {!report.available && (
                    <span className="px-2 py-1 rounded-full bg-slate-700 text-slate-400 text-xs font-medium">
                        Coming Soon
                    </span>
                )}
            </div>
            <h3 className={`text-xl font-semibold mb-2 ${accentClasses[report.color]}`}>
                {report.title}
            </h3>
            <p className="text-slate-400 text-sm">{report.description}</p>

            {report.available && (
                <div className="mt-4 flex items-center text-sm text-slate-500">
                    <span>View report</span>
                    <svg className="w-4 h-4 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                </div>
            )}
        </div>
    );

    if (report.available) {
        return <Link href={report.href}>{content}</Link>;
    }

    return content;
}
