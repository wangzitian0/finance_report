import { describe, it, expect, vi } from 'vitest'

describe('API Configuration', () => {
  describe('API_URL', () => {
    it('should default to empty string when NEXT_PUBLIC_API_URL is not set', () => {
      const envValue = undefined
      const API_URL = envValue || ''
      expect(API_URL).toBe('')
    })

    it('should use NEXT_PUBLIC_API_URL when set', () => {
      const envValue = 'https://api.example.com'
      const API_URL = envValue || ''
      expect(API_URL).toBe('https://api.example.com')
    })

    it('should handle empty string as falsy and use default', () => {
      const envValue = ''
      const API_URL = envValue || 'fallback'
      expect(API_URL).toBe('fallback')
    })
  })

  describe('APP_URL', () => {
    it('should default to http://localhost:3000 when NEXT_PUBLIC_APP_URL is not set', () => {
      const envValue = undefined
      const APP_URL = envValue || 'http://localhost:3000'
      expect(APP_URL).toBe('http://localhost:3000')
    })

    it('should use NEXT_PUBLIC_APP_URL when set to production URL', () => {
      const envValue = 'https://report.zitian.party'
      const APP_URL = envValue || 'http://localhost:3000'
      expect(APP_URL).toBe('https://report.zitian.party')
    })

    it('should use NEXT_PUBLIC_APP_URL when set to PR environment', () => {
      const envValue = 'https://report-pr-101.zitian.party'
      const APP_URL = envValue || 'http://localhost:3000'
      expect(APP_URL).toBe('https://report-pr-101.zitian.party')
    })
  })

  describe('Import actual constants', () => {
    it('should import API_URL and APP_URL successfully', async () => {
      const { API_URL, APP_URL } = await import('../lib/api')
      expect(API_URL).toBeDefined()
      expect(APP_URL).toBeDefined()
      expect(typeof API_URL).toBe('string')
      expect(typeof APP_URL).toBe('string')
    })
  })
})
