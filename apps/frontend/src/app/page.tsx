import Link from 'next/link'

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700/50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-xl flex items-center justify-center">
              <span className="text-white font-bold text-lg">₿</span>
            </div>
            <span className="text-white font-semibold text-xl">Finance Report</span>
          </div>
          <nav className="flex items-center gap-6">
            <Link href="/ping-pong" className="text-slate-400 hover:text-white transition-colors text-sm">
              Ping-Pong Demo
            </Link>
            <a 
              href="/api/docs" 
              className="text-slate-400 hover:text-white transition-colors text-sm"
              target="_blank"
              rel="noopener noreferrer"
            >
              API Docs
            </a>
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <main className="max-w-7xl mx-auto px-6 py-20">
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold text-white mb-6">
            Personal Finance Management
          </h1>
          <p className="text-xl text-slate-400 max-w-2xl mx-auto">
            Double-entry bookkeeping with AI-powered document parsing and bank reconciliation.
          </p>
        </div>

        {/* Feature Cards */}
        <div className="grid md:grid-cols-3 gap-6 mb-16">
          <FeatureCard
            icon="📊"
            title="Double-Entry Bookkeeping"
            description="Proper accounting with journal entries that always balance. Track assets, liabilities, equity, income, and expenses."
          />
          <FeatureCard
            icon="🏦"
            title="Bank Reconciliation"
            description="Import bank statements and match transactions automatically with confidence scoring."
          />
          <FeatureCard
            icon="🤖"
            title="AI Document Parsing"
            description="Upload receipts and invoices. Gemini AI extracts transaction details automatically."
          />
        </div>

        {/* Coming Soon */}
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-8 text-center">
          <div className="inline-flex items-center gap-2 bg-amber-500/10 text-amber-400 px-4 py-2 rounded-full text-sm font-medium mb-4">
            <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse"></span>
            Under Development
          </div>
          <h2 className="text-2xl font-semibold text-white mb-3">
            Full Application Coming Soon
          </h2>
          <p className="text-slate-400 max-w-lg mx-auto">
            The core accounting engine is being built. Check back soon for the complete personal finance management experience.
          </p>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-700/50 mt-20">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between text-sm text-slate-500">
            <p>Built with FastAPI + Next.js</p>
            <div className="flex items-center gap-4">
              <Link href="/ping-pong" className="hover:text-slate-300 transition-colors">
                Demo
              </Link>
              <a href="/api/docs" className="hover:text-slate-300 transition-colors">
                API
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}

function FeatureCard({ icon, title, description }: { icon: string; title: string; description: string }) {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 hover:bg-slate-800/50 transition-colors">
      <div className="text-4xl mb-4">{icon}</div>
      <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-slate-400 text-sm">{description}</p>
    </div>
  )
}
