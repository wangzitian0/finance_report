import { describe, it, expect } from 'vitest'
import { API_URL, APP_URL } from '../lib/api'

describe('API Configuration', () => {
  it('should have default API_URL', () => {
    expect(API_URL).toBeDefined()
  })

  it('should have default APP_URL', () => {
    expect(APP_URL).toBe('http://localhost:3000')
  })
})
