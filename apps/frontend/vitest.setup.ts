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

afterEach(() => {
  void import("@testing-library/react").then(({ cleanup }) => cleanup())
})
