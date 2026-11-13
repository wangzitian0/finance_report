import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { HINT_KEYWORD_MAX_LENGTH, HINT_MAX_KEYWORDS, HINT_NOTE_MAX_LENGTH } from "@/components/review/StatementRuns";

type SchemaNode = { maxItems?: number; maxLength?: number; minLength?: number; items?: SchemaNode; anyOf?: SchemaNode[]; type?: string };
const openapi = JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../openapi.json"), "utf-8")) as {
  components: { schemas: Record<string, { properties: Record<string, SchemaNode> }> };
};

describe("the Run again limits follow the OpenAPI spec", () => {
  const hints = openapi.components.schemas.RunHints.properties;

  it("AC-extraction.2994.75 the keyword count, keyword length and note length match openapi.json", () => {
    expect(hints.keywords.maxItems).toBe(HINT_MAX_KEYWORDS);
    expect(hints.keywords.items?.maxLength).toBe(HINT_KEYWORD_MAX_LENGTH);
    const noteSchema = (hints.note.anyOf ?? []).find((branch) => branch.type === "string");
    expect(noteSchema?.maxLength).toBe(HINT_NOTE_MAX_LENGTH);
  });
});
