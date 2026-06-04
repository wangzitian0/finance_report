import { NextResponse } from "next/server"

export const dynamic = "force-dynamic"

export function GET() {
  const gitSha = process.env.GIT_COMMIT_SHA || "unknown"

  return NextResponse.json(
    {
      git_sha: gitSha,
      version: gitSha,
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  )
}
