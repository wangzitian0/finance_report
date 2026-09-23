import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { middleware } from '../middleware'

describe('Next.js Middleware Dynamic Content Security Policy', () => {
  const originalEnv = { ...process.env }

  beforeEach(() => {
    vi.resetModules()
    process.env = { ...originalEnv }
  })

  afterEach(() => {
    process.env = originalEnv
  })

  it('attaches Content-Security-Policy header with default public endpoints when env is unconfigured', () => {
    delete process.env.OPENPANEL_API_URL
    delete process.env.OPENPANEL_SCRIPT_URL
    delete process.env.EXTRA_CSP_SCRIPT_SRC
    delete process.env.EXTRA_CSP_CONNECT_SRC

    const request = new NextRequest('http://localhost:3000/')
    const response = middleware(request)

    const csp = response.headers.get('Content-Security-Policy')
    expect(csp).toBeTruthy()
    expect(csp).toContain("script-src 'self' 'unsafe-inline' https://api.openpanel.dev")
    expect(csp).toContain("connect-src 'self' https://api.openpanel.dev")
    expect(csp).not.toContain('zitian.party')
  })

  it('dynamically derives Content-Security-Policy at runtime when OPENPANEL_API_URL and OPENPANEL_SCRIPT_URL are set', () => {
    process.env.OPENPANEL_API_URL = 'https://openpanel.zitian.party/api'
    process.env.OPENPANEL_SCRIPT_URL = 'https://openpanel.zitian.party/op1.js'

    const request = new NextRequest('http://localhost:3000/')
    const response = middleware(request)

    const csp = response.headers.get('Content-Security-Policy')
    expect(csp).toBeTruthy()
    expect(csp).toContain('https://openpanel.zitian.party')
    expect(csp).toMatch(/script-src [^;]*https:\/\/openpanel\.zitian\.party/)
    expect(csp).toMatch(/connect-src [^;]*https:\/\/openpanel\.zitian\.party/)
  })
})
