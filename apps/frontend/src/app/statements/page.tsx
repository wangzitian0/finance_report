export default function StatementsPage() {
    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-8">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <p className="text-xs uppercase tracking-[0.3em] text-emerald-500 mb-2">
                            Import & Parse
                        </p>
                        <h1 className="text-4xl font-semibold text-white">Bank Statements</h1>
                        <p className="mt-2 text-slate-400">
                            Upload bank statements for AI-powered parsing and reconciliation.
                        </p>
                    </div>
                </div>

                {/* Upload Area */}
                <div className="rounded-2xl border-2 border-dashed border-slate-600 bg-slate-800/20 p-12 text-center mb-8 opacity-60 cursor-not-allowed">
                    <div className="flex flex-col items-center">
                        <div className="w-16 h-16 rounded-2xl bg-slate-700/50 flex items-center justify-center mb-4">
                            <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                            </svg>
                        </div>
                        <p className="text-white font-medium mb-1">Drop files here to upload</p>
                        <p className="text-sm text-slate-500">PDF, CSV, or XLSX (max 10MB)</p>
                    </div>
                </div>

                {/* Coming Soon Card */}
                <div className="rounded-2xl border border-slate-700/50 bg-slate-800/30 p-12 text-center">
                    <div className="inline-flex items-center gap-2 bg-amber-500/10 text-amber-400 px-4 py-2 rounded-full text-sm font-medium mb-6">
                        <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                        Under Development
                    </div>

                    <h2 className="text-2xl font-semibold text-white mb-4">
                        Statement Upload Coming Soon
                    </h2>

                    <p className="text-slate-400 max-w-lg mx-auto mb-8">
                        Upload bank statements in PDF or CSV format. Our AI will automatically
                        extract transactions and prepare them for reconciliation.
                    </p>

                    <div className="grid grid-cols-3 gap-4 max-w-xl mx-auto text-left">
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">🤖</span>
                            <h3 className="text-sm font-medium text-white">AI Extraction</h3>
                            <p className="text-xs text-slate-500 mt-1">Gemini-powered parsing</p>
                        </div>
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">📊</span>
                            <h3 className="text-sm font-medium text-white">Multi-Format</h3>
                            <p className="text-xs text-slate-500 mt-1">PDF, CSV, XLSX</p>
                        </div>
                        <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/30">
                            <span className="text-2xl mb-2 block">✓</span>
                            <h3 className="text-sm font-medium text-white">Validation</h3>
                            <p className="text-xs text-slate-500 mt-1">Balance verification</p>
                        </div>
                    </div>
                </div>

                {/* Recent Uploads Table (placeholder) */}
                <div className="mt-8 rounded-2xl border border-slate-700/50 bg-slate-800/30 overflow-hidden">
                    <div className="px-6 py-4 border-b border-slate-700/50">
                        <h3 className="text-lg font-medium text-white">Recent Uploads</h3>
                    </div>
                    <div className="p-8 text-center text-slate-500">
                        No statements uploaded yet
                    </div>
                </div>
            </div>
        </div>
    );
}
