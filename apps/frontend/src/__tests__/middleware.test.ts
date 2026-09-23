import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { middleware } from '../middleware'

describe('AC1.10.4 Next.js Middleware Dynamic Content Security Policy', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('attaches Content-Security-Policy header with default public endpoints when env is unconfigured', () => {
    vi.stubEnv('OPENPANEL_API_URL', '')
    vi.stubEnv('OPENPANEL_SCRIPT_URL', '')
    vi.stubEnv('EXTRA_CSP_SCRIPT_SRC', '')
    vi.stubEnv('EXTRA_CSP_CONNECT_SRC', '')

    const request = new NextRequest('http://localhost:3000/')
    const response = middleware(request)

    const csp = response.headers.get('Content-Security-Policy')
    expect(csp).toBeTruthy()
    expect(csp).toContain("script-src 'self' 'unsafe-inline' https://api.openpanel.dev")
    expect(csp).toContain("connect-src 'self' https://api.openpanel.dev")
    expect(csp).not.toContain('zitian.party')
  })

  it('dynamically derives Content-Security-Policy at runtime when OPENPANEL_API_URL and OPENPANEL_SCRIPT_URL are set', () => {
    vi.stubEnv('OPENPANEL_API_URL', 'https://openpanel.zitian.party/api')
    vi.stubEnv('OPENPANEL_SCRIPT_URL', 'https://openpanel.zitian.party/op1.js')

    const request = new NextRequest('http://localhost:3000/')
    const response = middleware(request)

    const csp = response.headers.get('Content-Security-Policy')
    expect(csp).toBeTruthy()
    expect(csp).toContain('https://openpanel.zitian.party')
    expect(csp).toMatch(/script-src [^;]*https:\/\/openpanel\.zitian\.party/)
    expect(csp).toMatch(/connect-src [^;]*https:\/\/openpanel\.zitian\.party/)
  })

  it('dynamically derives connect-src from NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT and NEXT_PUBLIC_API_URL', () => {
    vi.stubEnv('NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT', 'https://otel.zitian.party/v1/traces')
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.zitian.party')

    const request = new NextRequest('http://localhost:3000/')
    const response = middleware(request)

    const csp = response.headers.get('Content-Security-Policy')
    expect(csp).toBeTruthy()
    expect(csp).toMatch(/connect-src [^;]*https:\/\/otel\.zitian\.party/)
    expect(csp).toMatch(/connect-src [^;]*https:\/\/api\.zitian\.party/)
  })
})
