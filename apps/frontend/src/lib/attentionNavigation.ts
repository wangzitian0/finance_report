export const ATTENTION_SOURCE_PARAM = "from";
export const ATTENTION_SOURCE_VALUE = "attention";
/** The Needs you tab of `/audit`: the confidence queue and the AI suggestions (#2646). */
export const NEEDS_YOU_HREF = "/audit?tab=needs-you";
export const ATTENTION_RETURN_HREF = NEEDS_YOU_HREF;
export const ATTENTION_RETURN_LABEL = "Back to Needs Confirmation";

interface SearchParamReader {
  get(name: string): string | null;
}

export function isAttentionOrigin(searchParams: SearchParamReader | null | undefined): boolean {
  return searchParams?.get(ATTENTION_SOURCE_PARAM) === ATTENTION_SOURCE_VALUE;
}

export function withAttentionSource(href: string): string {
  const url = new URL(href, "https://finance-report.local");
  url.searchParams.set(ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE);

  const query = url.searchParams.toString();
  return `${url.pathname}${query ? `?${query}` : ""}${url.hash}`;
}
