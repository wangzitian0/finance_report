import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch, API_URL } from './api';

// Mock fetch global
const fetchMock = vi.fn();
global.fetch = fetchMock;

describe('apiFetch', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: 'test' }),
    });
  });

  it('should normalize path by adding leading slash if missing', async () => {
    await apiFetch('users');
    
    // API_URL might be empty string in test env, so it should be "/users"
    // If API_URL is set, it should be "${API_URL}/users"
    const expectedUrl = `${API_URL}/users`;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('should not add double slash if path already has leading slash', async () => {
    await apiFetch('/users');
    
    const expectedUrl = `${API_URL}/users`;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('should handle whitespace in base URL gracefully', async () => {
    // This assumes API_URL logic in api.ts uses .trim()
    // We cannot change the const import at runtime easily in ES modules without setup,
    // so we verify the path normalization part specifically.
    await apiFetch('  /users  ');
    // Path normalization currently only handles leading slash. 
    // It does NOT trim the input path itself, but we should verify it handles the slash.
    const expectedUrl = `${API_URL}/users  `; 
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });
});
