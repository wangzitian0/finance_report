export default function AccountsPage() {
    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-8">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <p className="text-xs uppercase tracking-[0.3em] text-emerald-500 mb-2">
                            Chart of Accounts
                        </p>
                        <h1 className="text-4xl font-semibold text-white">Accounts</h1>
                        <p className="mt-2 text-slate-400">
                            Manage your chart of accounts with double-entry bookkeeping structure.
                        </p>
                    </div>
                    <button
                        disabled
                        className="px-5 py-2.5 rounded-xl bg-emerald-500/20 text-emerald-400 font-medium
                       opacity-50 cursor-not-allowed flex items-center gap-2"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                        Add Account
                    </button>
                </div>

                {/* Account Type Tabs */}
                <div className="flex gap-2 mb-6">
                    {["All", "Assets", "Liabilities", "Equity", "Income", "Expenses"].map((type) => (
                        <button
                            key={type}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors
                ${type === "All"
                                    ? "bg-slate-700 text-white"
                                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                                }`}
                        >
                            {type}
                        </button>
                    ))}
                </div>

                {/* Coming Soon Card */}
                <div className="rounded-2xl border border-slate-700/50 bg-slate-800/30 p-12 text-center">
                    <div className="inline-flex items-center gap-2 bg-amber-500/10 text-amber-400 px-4 py-2 rounded-full text-sm font-medium mb-6">
                        <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                        Under Development
                    </div>

                    <h2 className="text-2xl font-semibold text-white mb-4">
                        Accounts Grid Coming Soon
                    </h2>

                    <p className="text-slate-400 max-w-lg mx-auto mb-8">
                        This page will display your chart of accounts with full CRUD capabilities.
                        Create, edit, and organize accounts in a hierarchical tree structure.
                    </p>

                    <div className="grid grid-cols-3 gap-4 max-w-xl mx-auto text-left">
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">🏦</span>
                            <h3 className="text-sm font-medium text-white">Account Hierarchy</h3>
                            <p className="text-xs text-slate-500 mt-1">Parent/child structure</p>
                        </div>
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">💱</span>
                            <h3 className="text-sm font-medium text-white">Multi-Currency</h3>
                            <p className="text-xs text-slate-500 mt-1">Per-account currency</p>
                        </div>
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">📊</span>
                            <h3 className="text-sm font-medium text-white">Balances</h3>
                            <p className="text-xs text-slate-500 mt-1">Real-time calculation</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
