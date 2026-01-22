import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiFetch, apiUpload, API_URL } from './api';

// Mock fetch global
const fetchMock = vi.fn();
global.fetch = fetchMock;

// Mock window.location
const originalLocation = window.location;
delete (window as any).location;
window.location = { ...originalLocation, href: '' } as Location;

describe('apiFetch', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    window.location.href = '';
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: 'test' }),
    });
  });

  afterEach(() => {
    window.location = originalLocation;
  });

  it('should normalize path by adding leading slash if missing', async () => {
    await apiFetch('users');
    
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

  it('should redirect to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });

  it('should throw error on 500 server error without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'Internal server error' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Internal server error');
    expect(window.location.href).toBe(''); // No redirect
  });

  it('should throw error on 404 not found without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: 'Not found' }),
    });

    await expect(apiFetch('/api/users/123')).rejects.toThrow('Not found');
    expect(window.location.href).toBe(''); // No redirect
  });
});

describe('apiUpload', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    window.location.href = '';
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'uploaded' }),
    });
  });

  it('should redirect to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    const formData = new FormData();
    formData.append('file', new Blob(['test']));

    await expect(apiUpload('/api/statements/upload', formData)).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });
});
