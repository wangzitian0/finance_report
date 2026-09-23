import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { buildContentSecurityPolicy } from '../next.config.mjs'

export function middleware(request: NextRequest) {
  const response = NextResponse.next()
  const csp = buildContentSecurityPolicy()
  response.headers.set('Content-Security-Policy', csp)
  return response
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
}
