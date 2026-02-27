import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// localStorage mock (must be set before importing api module)
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
vi.stubGlobal('localStorage', localStorageMock);

function makeFetchMock(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    headers: {
      get: (name: string) => headers[name] ?? null,
    },
  });
}

describe('apiFetch', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  it('AC16.10.1 returns JSON on 200 response', async () => {
    const fetchMock = makeFetchMock(200, { id: 1, name: 'test' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    const result = await apiFetch<{ id: number; name: string }>('/api/test');

    expect(result).toEqual({ id: 1, name: 'test' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/test'),
      expect.objectContaining({ headers: expect.any(Object) })
    );
  });

  it('AC16.10.2 returns undefined on 204 No Content', async () => {
    const fetchMock = makeFetchMock(204, null);
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    const result = await apiFetch('/api/test');

    expect(result).toBeUndefined();
  });

  it('AC16.10.3 throws with detail message on JSON error response', async () => {
    const fetchMock = makeFetchMock(400, { detail: 'Validation failed' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    await expect(apiFetch('/api/test')).rejects.toThrow('Validation failed');
  });

  it('AC16.10.4 throws with raw text on non-JSON error response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal Server Error'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    await expect(apiFetch('/api/test')).rejects.toThrow('Internal Server Error');
  });

  it('AC16.10.13 normalizes path without leading slash', async () => {
    const fetchMock = makeFetchMock(200, {});
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    await apiFetch('api/no-slash');

    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toMatch(/\/api\/no-slash/);
  });

  it('AC16.10.14 includes Authorization header when token present', async () => {
    localStorageMock.setItem('finance_access_token', 'test-jwt-token');
    const fetchMock = makeFetchMock(200, {});
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../lib/api');
    await apiFetch('/api/secure');

    const calledHeaders = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(calledHeaders['Authorization']).toBe('Bearer test-jwt-token');
  });
});

describe('resetRedirectGuard', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  it('AC16.10.6 resetRedirectGuard is exported and callable', async () => {
    const { resetRedirectGuard } = await import('../lib/api');
    expect(() => resetRedirectGuard()).not.toThrow();
  });
});

describe('apiDelete', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  it('AC16.10.7 succeeds on 200 response', async () => {
    const fetchMock = makeFetchMock(200, '');
    vi.stubGlobal('fetch', fetchMock);

    const { apiDelete } = await import('../lib/api');
    await expect(apiDelete('/api/resource/1')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/resource/1'),
      expect.objectContaining({ method: 'DELETE' })
    );
  });

  it('AC16.10.8 throws on non-ok response', async () => {
    const fetchMock = makeFetchMock(404, '');
    vi.stubGlobal('fetch', fetchMock);

    const { apiDelete } = await import('../lib/api');
    await expect(apiDelete('/api/resource/missing')).rejects.toThrow('Delete failed with 404');
  });
});

describe('apiStream', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  it('AC16.10.9 returns response and sessionId on success', async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      text: () => Promise.resolve(''),
      json: () => Promise.resolve({}),
      headers: { get: (name: string) => name === 'X-Session-Id' ? 'sess-abc' : null },
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse));

    const { apiStream } = await import('../lib/api');
    const result = await apiStream('/api/stream');

    expect(result.response).toBe(mockResponse);
    expect(result.sessionId).toBe('sess-abc');
  });

  it('AC16.10.10 throws on non-ok response', async () => {
    const fetchMock = makeFetchMock(503, { detail: 'Service Unavailable' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiStream } = await import('../lib/api');
    await expect(apiStream('/api/stream')).rejects.toThrow('Service Unavailable');
  });
});

describe('apiUpload', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', localStorageMock);
  });

  it('AC16.10.11 returns JSON on 200 response', async () => {
    const fetchMock = makeFetchMock(200, { uploaded: true });
    vi.stubGlobal('fetch', fetchMock);

    const { apiUpload } = await import('../lib/api');
    const fd = new FormData();
    fd.append('file', new Blob(['data']), 'test.pdf');

    const result = await apiUpload<{ uploaded: boolean }>('/api/upload', fd);
    expect(result).toEqual({ uploaded: true });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/upload'),
      expect.objectContaining({ method: 'POST', body: fd })
    );
  });

  it('AC16.10.12 returns undefined on 204 No Content', async () => {
    const fetchMock = makeFetchMock(204, null);
    vi.stubGlobal('fetch', fetchMock);

    const { apiUpload } = await import('../lib/api');
    const fd = new FormData();
    const result = await apiUpload('/api/upload', fd);
    expect(result).toBeUndefined();
  });
});
