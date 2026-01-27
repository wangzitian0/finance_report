/**
 * API Catch-All Route Handler
 *
 * Catches /api/* requests that reach Next.js when backend is unreachable.
 *
 * In production with Traefik (see docker-compose.yml):
 * - Backend has priority=10 for /api/* routes
 * - Frontend has priority=1 as catch-all for /*
 * - If /api/* requests reach Next.js, this returns JSON 503 instead of HTML 404
 *
 * @see https://github.com/wangzitian0/finance_report/issues/210
 */
import { type NextRequest, NextResponse } from "next/server";

const SERVICE_UNAVAILABLE_RESPONSE = {
  detail: "API service temporarily unavailable. Please try again in a moment.",
  code: "SERVICE_UNAVAILABLE",
};

function logAndRespond(method: string, request: NextRequest): NextResponse {
  console.error(
    JSON.stringify({
      level: "error",
      message: "Backend unavailable - serving 503 fallback",
      method,
      path: request.nextUrl.pathname,
      timestamp: new Date().toISOString(),
    })
  );
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}

export async function GET(request: NextRequest) {
  return logAndRespond("GET", request);
}

export async function POST(request: NextRequest) {
  return logAndRespond("POST", request);
}

export async function PUT(request: NextRequest) {
  return logAndRespond("PUT", request);
}

export async function PATCH(request: NextRequest) {
  return logAndRespond("PATCH", request);
}

export async function DELETE(request: NextRequest) {
  return logAndRespond("DELETE", request);
}
