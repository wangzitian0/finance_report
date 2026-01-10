'use client'

import { useState, useEffect, useCallback } from 'react'

interface PingState {
  state: 'ping' | 'pong'
  toggle_count: number
  updated_at: string | null
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function Home() {
  const [pingState, setPingState] = useState<PingState | null>(null)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchState = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/ping`)
      if (!res.ok) throw new Error('Failed to fetch state')
      const data = await res.json()
      setPingState(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, []) // API_URL is a module-level constant, no need in deps

  const toggleState = async () => {
    setToggling(true)
    try {
      const res = await fetch(`${API_URL}/ping/toggle`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to toggle state')
      const data = await res.json()
      setPingState(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setToggling(false)
    }
  }

  useEffect(() => {
    fetchState()
  }, [fetchState])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 flex items-center justify-center p-8">
      <div className="bg-white/10 backdrop-blur-lg rounded-3xl p-12 shadow-2xl border border-white/20 max-w-md w-full">
        <h1 className="text-4xl font-bold text-white text-center mb-2">
          Finance Report
        </h1>
        <p className="text-gray-300 text-center mb-8">
          Ping-Pong Demo
        </p>

        {loading ? (
          <div className="flex justify-center">
            <div className="animate-spin rounded-full h-16 w-16 border-4 border-purple-500 border-t-transparent"></div>
          </div>
        ) : error ? (
          <div className="bg-red-500/20 border border-red-500/50 rounded-xl p-4 text-center">
            <p className="text-red-300">{error}</p>
            <button
              onClick={fetchState}
              className="mt-4 px-4 py-2 bg-red-500/30 hover:bg-red-500/50 rounded-lg text-white transition-all"
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="text-center">
            <div
              className={`text-8xl font-black mb-6 transition-all duration-500 ${pingState?.state === 'ping'
                  ? 'text-cyan-400 animate-pulse'
                  : 'text-pink-400 animate-bounce'
                }`}
            >
              {pingState?.state?.toUpperCase()}
            </div>

            <button
              onClick={toggleState}
              disabled={toggling}
              className={`
                w-full py-4 px-8 rounded-2xl text-xl font-bold
                transition-all duration-300 transform
                ${toggling
                  ? 'bg-gray-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-cyan-500 to-pink-500 hover:from-cyan-400 hover:to-pink-400 hover:scale-105 active:scale-95'
                }
                text-white shadow-lg
              `}
            >
              {toggling ? 'Toggling...' : 'Toggle State'}
            </button>

            <div className="mt-8 text-gray-400 text-sm space-y-1">
              <p>Toggle count: <span className="text-white font-mono">{pingState?.toggle_count}</span></p>
              {pingState?.updated_at && (
                <p>Last toggled: <span className="text-white font-mono">
                  {new Date(pingState.updated_at).toLocaleTimeString()}
                </span></p>
              )}
            </div>
          </div>
        )}

        <div className="mt-8 pt-6 border-t border-white/10 text-center text-gray-500 text-xs">
          <p>Backend: FastAPI + PostgreSQL</p>
          <p>Frontend: Next.js + TailwindCSS</p>
        </div>
      </div>
    </div>
  )
}
