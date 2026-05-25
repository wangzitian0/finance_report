import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch, apiUpload, API_URL, resetRedirectGuard } from './api';

// Mock fetch global
const fetchMock = vi.fn();
global.fetch = fetchMock;

// Create a mock localStorage
const localStorageMock = {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
});

// Create a mutable mock location object
const mockLocation = { href: '' };

// Mock window.location using Object.defineProperty
Object.defineProperty(window, 'location', {
  value: mockLocation,
  writable: true,
  configurable: true,
});

describe('apiFetch', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    // Default: no token (unauthenticated)
    localStorageMock.getItem.mockReturnValue(null);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: 'test' }),
    });
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

  it('AC16.10.5 should redirect to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
  });

  it('should throw error on 500 server error without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'Internal server error' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Internal server error');
    expect(mockLocation.href).toBe(''); // No redirect
  });

  it('should throw error on 404 not found without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: 'Not found' }),
    });

    await expect(apiFetch('/api/users/123')).rejects.toThrow('Not found');
    expect(mockLocation.href).toBe(''); // No redirect
  });

  it('should fallback to raw text when body is non-json', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => "plain text error"
    });

    await expect(apiFetch('/api/bad')).rejects.toThrow('plain text error');
  });

  it('should handle SSR window undefined guard in handle401Redirect', async () => {
    const oldWindow = (globalThis as { window?: unknown }).window;
    vi.stubGlobal('window', undefined);

    fetchMock.mockResolvedValue({ ok: false, status: 401, text: async () => JSON.stringify({ detail: 'no' }) });

    await expect(apiFetch('/api/ssr')).rejects.toThrow('Authentication required');

    vi.stubGlobal('window', oldWindow);
  });
});

describe('apiUpload', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    // Default: no token (unauthenticated)
    localStorageMock.getItem.mockReturnValue(null);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'uploaded' }),
    });
  });

  it('apiStream should redirect on 401', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401, text: async () => JSON.stringify({ detail: 'x' }) });
    const { apiStream } = await import('./api');
    await expect(apiStream('/stream')).rejects.toThrow('Authentication required');
  });

  it('apiDelete should throw for non-401 errors', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => 'err' });
    const { apiDelete } = await import('./api');
    await expect(apiDelete('/del')).rejects.toThrow('Delete failed with 500');
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
    expect(mockLocation.href).toBe('/login');
  });
});
