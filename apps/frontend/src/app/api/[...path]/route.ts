/**
 * API Catch-All Route Handler
 *
 * This route catches any /api/* requests that reach Next.js when the backend
 * is unavailable (e.g., during heavy parsing load in production).
 *
 * In production with Traefik:
 * - Backend has priority=10 for /api/* routes
 * - Frontend has priority=1 as catch-all
 * - When backend health check fails, Traefik falls through to frontend
 *
 * Without this handler, Next.js returns HTML "404 page not found" which breaks
 * frontend JSON parsing. This handler returns proper JSON 503 responses.
 *
 * @see https://github.com/wangzitian0/finance_report/issues/210
 */
import { NextResponse } from "next/server";

const SERVICE_UNAVAILABLE_RESPONSE = {
  detail: "API service temporarily unavailable. Please try again in a moment.",
  code: "SERVICE_UNAVAILABLE",
};

export async function GET() {
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}

export async function POST() {
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}

export async function PUT() {
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}

export async function PATCH() {
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}

export async function DELETE() {
  return NextResponse.json(SERVICE_UNAVAILABLE_RESPONSE, { status: 503 });
}
