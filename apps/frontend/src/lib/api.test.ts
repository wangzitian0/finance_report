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

  it('should preserve whitespace in path while normalizing leading slash', async () => {
    await apiFetch('users  ');

    const expectedUrl = `${API_URL}/users  `;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });
});
