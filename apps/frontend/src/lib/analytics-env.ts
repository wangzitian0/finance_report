/**
 * C5 (Infra-014): page-view analytics must be configured in deployed, non-preview
 * environments (staging/production). A missing client id there means analytics is
 * silently off — a misconfiguration the app surfaces (server log → SigNoz) instead
 * of failing silently, but never by throwing (that would break SSR). Preview
 * (report-pr-N) and local intentionally have no OpenPanel, so they stay silent.
 *
 * Kept in a plain module (not layout.tsx) because Next.js forbids arbitrary
 * exports from a Layout file.
 */
export function analyticsClientIdMissingInDeployedEnv(
  clientId: string | undefined,
  appUrl: string | undefined,
): boolean {
  if (clientId && clientId.trim()) return false;
  const url = (appUrl ?? "").trim();
  return url.startsWith("https://") && !url.includes("-pr-") && !url.includes("localhost");
}
