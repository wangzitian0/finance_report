export const ATTENTION_SOURCE_PARAM = "from";
export const ATTENTION_SOURCE_VALUE = "attention";
export const ATTENTION_RETURN_HREF = "/attention";
export const ATTENTION_RETURN_LABEL = "Back to Attention queue";

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
