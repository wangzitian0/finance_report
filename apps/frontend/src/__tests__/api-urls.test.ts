import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../lib/auth', () => ({
  getAccessToken: () => null,
  getUserId: () => null,
}))

describe('API URL Configuration Scenarios', () => {
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL
  const originalAppUrl = process.env.NEXT_PUBLIC_APP_URL

  beforeEach(() => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', originalApiUrl)
    vi.stubEnv('NEXT_PUBLIC_APP_URL', originalAppUrl)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  describe('Development Environment', () => {
    it('should accept empty API_URL for same-origin requests', () => {
      vi.stubEnv('NEXT_PUBLIC_API_URL', '')
      const API_URL = (process.env.NEXT_PUBLIC_API_URL || '').trim().replace(/\/$/, '')
      expect(API_URL).toBe('')
    })

    it('should accept localhost API_URL for development', () => {
      vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000')
      const API_URL = (process.env.NEXT_PUBLIC_API_URL || '').trim().replace(/\/$/, '')
      expect(API_URL).toEqual(expect.stringMatching(/^http:\/\/localhost(?::\d+)?$/))
    })

    it('should use localhost:3000 as default APP_URL', () => {
      vi.stubEnv('NEXT_PUBLIC_APP_URL', undefined)
      const APP_URL = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'
      expect(APP_URL).toBe('http://localhost:3000')
    })
  })

  describe('Production Environment', () => {
    it('should construct correct API path with empty API_URL', () => {
      const API_URL = ''
      const path = '/api/accounts'
      const fullPath = `${API_URL}${path}`
      expect(fullPath).toBe('/api/accounts')
    })

    it('should construct correct API path with absolute API_URL', () => {
      const API_URL = 'https://report.example.com'
      const path = '/api/accounts'
      const fullPath = `${API_URL}${path}`
      expect(fullPath).toBe('https://report.example.com/api/accounts')
    })

    it('AC7.9.5 does not proxy production API routes to localhost', async () => {
      vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://report.example.com')
      vi.stubEnv('NODE_ENV', 'production')

      const { default: nextConfig } = await import('../../next.config.mjs')
      const rewrites = typeof nextConfig.rewrites === 'function'
        ? await nextConfig.rewrites()
        : []

      expect(JSON.stringify(rewrites)).not.toContain('localhost:8000')
    })

    it('AC1.10.4 configures browser security headers without unsafe eval', async () => {
      const { default: nextConfig } = await import('../../next.config.mjs')

      expect(typeof nextConfig.headers).toBe('function')
      const headerRules = typeof nextConfig.headers === 'function'
        ? await nextConfig.headers()
        : []
      const headers = Object.fromEntries(
        headerRules.flatMap((rule: { headers: Array<{ key: string; value: string }> }) =>
          rule.headers.map((header) => [header.key, header.value])
        )
      )

      expect(headers['Content-Security-Policy']).toContain("default-src 'self'")
      expect(headers['Content-Security-Policy']).toContain("frame-ancestors 'none'")
      expect(headers['Content-Security-Policy']).not.toContain("'unsafe-eval'")
      expect(headers['Strict-Transport-Security']).toContain('max-age=31536000')
      expect(headers['X-Frame-Options']).toBe('DENY')
      expect(headers['Referrer-Policy']).toBe('strict-origin-when-cross-origin')
      expect(headers['Permissions-Policy']).toContain('camera=()')
    })
  })

  describe('PR Environment', () => {
    it('should work with PR-specific domain', () => {
      const APP_URL = 'https://report-pr-101.example.com'
      expect(APP_URL).toMatch(/^https:\/\/report-pr-\d+\.example\.com$/)
    })
  })

  describe('URL Construction Logic', () => {
    it('should handle trailing slash correctly', () => {
      const rawUrl = 'https://api.example.com/'
      const API_URL = rawUrl.replace(/\/$/, '')
      const path = '/api/accounts'
      const fullPath = `${API_URL}${path}`
      expect(fullPath).toBe('https://api.example.com/api/accounts')
    })

    it('should handle missing leading slash in path', () => {
      const API_URL = 'https://api.example.com'
      const path = 'api/accounts'
      const fullPath = path.startsWith('/') ? `${API_URL}${path}` : `${API_URL}/${path}`
      expect(fullPath).toBe('https://api.example.com/api/accounts')
    })

    it('should handle whitespace in API_URL', () => {
      const rawUrl = '  https://api.example.com  '
      const API_URL = rawUrl.trim().replace(/\/$/, '')
      expect(API_URL).toBe('https://api.example.com')
    })
  })

  describe('Environment Variable Precedence', () => {
    it('should prioritize env var over default for API_URL', () => {
      const envValue = 'https://custom.api.com'
      const API_URL = envValue || ''
      expect(API_URL).toBe(envValue)
    })

    it('should prioritize env var over default for APP_URL', () => {
      const envValue = 'https://custom.app.com'
      const APP_URL = envValue || 'http://localhost:3000'
      expect(APP_URL).toBe(envValue)
    })

    it('should fall back to default when env var is empty string', () => {
      const envValue = ''
      const API_URL = envValue || 'https://fallback.com'
      expect(API_URL).toBe('https://fallback.com')
    })
  })

  describe('Dynamic Content Security Policy', () => {
    it('defaults to allowing standard OpenPanel cloud and contains no private infrastructure domains', async () => {
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toContain('script-src')
      expect(csp).toContain('https://api.openpanel.dev')
      expect(csp).not.toContain('zitian.party')
    })

    it('allows injecting private or wildcard domains via EXTRA_CSP_CONNECT_SRC', async () => {
      vi.stubEnv('EXTRA_CSP_CONNECT_SRC', 'https://*.zitian.party')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toMatch(/connect-src [^;]*https:\/\/\*\.zitian\.party/)
    })

    it('dynamically parses OPENPANEL_API_URL and OPENPANEL_SCRIPT_URL into CSP', async () => {
      vi.stubEnv('OPENPANEL_API_URL', 'https://custom-openpanel.example.com/api/v1')
      vi.stubEnv('OPENPANEL_SCRIPT_URL', 'https://cdn-openpanel.example.com/tracker.js')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toMatch(/script-src [^;]*https:\/\/custom-openpanel\.example\.com/)
      expect(csp).toMatch(/connect-src [^;]*https:\/\/custom-openpanel\.example\.com/)
      expect(csp).toMatch(/script-src [^;]*https:\/\/cdn-openpanel\.example\.com/)
    })

    it('supports EXTRA_CSP_CONNECT_SRC and EXTRA_CSP_SCRIPT_SRC', async () => {
      vi.stubEnv('EXTRA_CSP_CONNECT_SRC', 'https://extra-api.example.com https://extra-api2.example.com')
      vi.stubEnv('EXTRA_CSP_SCRIPT_SRC', 'https://extra-script.example.com')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toMatch(/connect-src [^;]*https:\/\/extra-api\.example\.com/)
      expect(csp).toMatch(/connect-src [^;]*https:\/\/extra-api2\.example\.com/)
      expect(csp).toMatch(/script-src [^;]*https:\/\/extra-script\.example\.com/)
    })

    it('safely handles and strips semicolons from EXTRA_CSP variables without corrupting directives', async () => {
      vi.stubEnv('EXTRA_CSP_CONNECT_SRC', 'https://semi1.example.com; https://semi2.example.com;')
      vi.stubEnv('EXTRA_CSP_SCRIPT_SRC', 'https://semi-script.example.com;')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toMatch(/connect-src [^;]*https:\/\/semi1\.example\.com/)
      expect(csp).toMatch(/connect-src [^;]*https:\/\/semi2\.example\.com/)
      expect(csp).toMatch(/script-src [^;]*https:\/\/semi-script\.example\.com/)
    })

    it('filters out opaque origins (null) from invalid or opaque URLs', async () => {
      vi.stubEnv('OPENPANEL_API_URL', 'data:text/plain;base64,SGVsbG8=')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).not.toContain('null')
    })

    it('validates EXTRA_CSP sources, preserving valid origins and quoted keywords while discarding invalid or opaque strings', async () => {
      vi.stubEnv('EXTRA_CSP_CONNECT_SRC', "invalid-opaque 'self' data:text/plain;base64,abc https://valid-extra.example.com/path")
      vi.stubEnv('EXTRA_CSP_SCRIPT_SRC', "opaque-token 'unsafe-eval' https://valid-script.example.com")
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toContain('https://valid-extra.example.com')
      expect(csp).toContain('https://valid-script.example.com')
      expect(csp).toContain("'unsafe-eval'")
      expect(csp).not.toContain('invalid-opaque')
      expect(csp).not.toContain('opaque-token')
      expect(csp).not.toMatch(/connect-src [^;]*data:/)
    })

    it('dynamically includes NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT and NEXT_PUBLIC_API_URL in connect-src', async () => {
      vi.stubEnv('NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT', 'https://otel.zitian.party/v1/traces')
      vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.com')
      const { buildContentSecurityPolicy } = await import('../../next.config.mjs')
      const csp = buildContentSecurityPolicy()
      expect(csp).toMatch(/connect-src [^;]*https:\/\/otel\.zitian\.party/)
      expect(csp).toMatch(/connect-src [^;]*https:\/\/api\.example\.com/)
    })
  })
})
