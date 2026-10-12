import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React, { type ReactNode } from "react"
import { expect, afterEach, vi } from 'vitest'
import * as matchers from '@testing-library/jest-dom/matchers'

expect.extend(matchers)

type HappyDomFetchInterceptor = {
  beforeAsyncRequest?: (event: { request: Request; window: Window & typeof globalThis }) => Response | null | undefined | Promise<Response | null | undefined>
}

type HappyDomGlobal = Window & typeof globalThis & {
  happyDOM?: {
    settings: {
      fetch: {
        interceptor?: HappyDomFetchInterceptor
      }
    }
  }
}

const happyDom = (window as HappyDomGlobal).happyDOM
const existingFetchInterceptor = happyDom?.settings.fetch.interceptor

if (happyDom) {
  happyDom.settings.fetch.interceptor = {
    ...(existingFetchInterceptor ?? {}),
    async beforeAsyncRequest(event) {
      if (event.request.url.startsWith("blob:")) {
        return new event.window.Response("", {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        })
      }

      return existingFetchInterceptor?.beforeAsyncRequest?.(event)
    },
  }
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

function QueryClientTestProvider({ children }: { children: ReactNode }) {
  const [queryClient] = React.useState(createQueryClient)

  return React.createElement(QueryClientProvider, { client: queryClient }, children)
}

function withDefaultWrapper<TOptions extends { wrapper?: React.ComponentType<{ children: ReactNode }> }>(
  options?: TOptions,
): TOptions {
  return {
    ...options,
    wrapper: options?.wrapper ?? QueryClientTestProvider,
  } as TOptions
}

vi.mock("@testing-library/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@testing-library/react")>()

  return {
    ...actual,
    render: (ui: Parameters<typeof actual.render>[0], options?: Parameters<typeof actual.render>[1]) =>
      actual.render(ui, withDefaultWrapper(options)),
    renderHook: (
      callback: Parameters<typeof actual.renderHook>[0],
      options?: Parameters<typeof actual.renderHook>[1],
    ) => actual.renderHook(callback, withDefaultWrapper(options)),
  }
})

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>()
  const api = await import("@/lib/api")
  const { API_OPERATIONS } = await import("@/lib/api-operations")

  function compatibilityPath(operationId: string, request: any): string {
    const definition = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId]
    if (!definition) return `/${operationId}`
    let path = definition.path.replace(/\{([^}]+)\}/g, (_placeholder, name: string) => {
      const value = request.path?.[name]
      if (value === undefined || value === null) {
        throw new Error(`Missing OpenAPI path parameter: ${name}`)
      }
      return encodeURIComponent(String(value))
    })
    if (request.query) {
      const query = new URLSearchParams()
      for (const [name, rawValue] of Object.entries(request.query)) {
        if (rawValue === undefined || rawValue === null) continue
        for (const value of Array.isArray(rawValue) ? rawValue : [rawValue]) {
          query.append(name, String(value))
        }
      }
      const encoded = query.toString()
      if (encoded) path = `${path}?${encoded}`
    }
    return path
  }

  return {
    ...actual,
    apiOperation: async (operationId: any, ...args: any[]) => {
      const request = (args[0] ?? {}) as any
      if (Reflect.has(api, "apiFetch") && vi.isMockFunction((api as any).apiFetch)) {
        const path = compatibilityPath(operationId, request)
        const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId]
        if (
          def?.method === "DELETE" &&
          request.body === undefined &&
          request.headers === undefined &&
          request.signal === undefined
        ) {
          if (Reflect.has(api, "apiDelete") && vi.isMockFunction((api as any).apiDelete)) {
            return (api as any).apiDelete(path)
          }
          return (api as any).apiFetch(path, { method: "DELETE" })
        }
        if (
          def?.method === "GET" &&
          request.body === undefined &&
          request.headers === undefined &&
          request.signal === undefined
        ) {
          return (api as any).apiFetch(path)
        }
        return (api as any).apiFetch(path, {
          method: def?.method ?? "POST",
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          headers: request.headers,
          signal: request.signal,
        })
      }
      return actual.apiOperation(operationId, ...args)
    },
    apiOperationStream: async (operationId: any, request: any) => {
      if (Reflect.has(api, "apiStream") && vi.isMockFunction((api as any).apiStream)) {
        const path = compatibilityPath(operationId, request)
        const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId]
        return (api as any).apiStream(path, {
          method: def?.method ?? "POST",
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          headers: request.headers,
          signal: request.signal,
        })
      }
      return actual.apiOperationStream(operationId, request)
    },
    apiOperationDownload: async (operationId: any, request: any) => {
      if (Reflect.has(api, "apiDownload") && vi.isMockFunction((api as any).apiDownload)) {
        const path = compatibilityPath(operationId, request)
        const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId]
        if (def?.method === "GET" && request.headers === undefined && request.signal === undefined) {
          return (api as any).apiDownload(path)
        }
        return (api as any).apiDownload(path, {
          method: def?.method ?? "GET",
          headers: request.headers,
          signal: request.signal,
        })
      }
      return actual.apiOperationDownload(operationId, request)
    },
    apiOperationUpload: async (operationId: any, request: any) => {
      if (Reflect.has(api, "apiUpload") && vi.isMockFunction((api as any).apiUpload)) {
        const path = compatibilityPath(operationId, request)
        const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId]
        return (api as any).apiUpload(path, request.body, {
          method: def?.method ?? "POST",
          headers: request.headers,
          signal: request.signal,
        })
      }
      return actual.apiOperationUpload(operationId, request)
    },
  }
})

afterEach(() => {
  void import("@testing-library/react").then(({ cleanup }) => cleanup())
})
