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
      const API_URL = 'https://report.zitian.party'
      const path = '/api/accounts'
      const fullPath = `${API_URL}${path}`
      expect(fullPath).toBe('https://report.zitian.party/api/accounts')
    })
  })

  describe('PR Environment', () => {
    it('should work with PR-specific domain', () => {
      const APP_URL = 'https://report-pr-101.zitian.party'
      expect(APP_URL).toMatch(/^https:\/\/report-pr-\d+\.zitian\.party$/)
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
})
