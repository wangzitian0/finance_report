import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs from apps/frontend, the directory that holds .eslintrc.json.
const FRONTEND_ROOT = process.cwd();
const LINT_TIMEOUT_MS = 30_000;

interface LintResult {
  messages: { ruleId: string | null; message: string }[];
}
interface EslintInstance {
  lintText(
    code: string,
    options: { filePath: string },
  ): Promise<LintResult[]>;
}
interface EslintClass {
  new (options: { cwd: string }): EslintInstance;
}

// eslint 8 ships no type declarations, so load it through a typed boundary.
const { ESLint } = createRequire(`${FRONTEND_ROOT}/package.json`)(
  "eslint",
) as { ESLint: EslintClass };
const eslint = new ESLint({ cwd: FRONTEND_ROOT });

// Built from parts so that this file holds no directive of its own.
const DIRECTIVE = ["eslint", "disable"].join("-");
const DIRECTIVE_PATTERN = new RegExp(`${DIRECTIVE}(?:-next-line|-line)?\\b(.*)$`);

/** True when a line holds a directive that turns this rule off: a bare one, or one that names it. */
function hidesTheRule(line: string): boolean {
  const match = DIRECTIVE_PATTERN.exec(line);
  if (match === null) return false;
  const rules = match[1]
    .split("--")[0]
    .replace(/\*\/.*$/, "")
    .split(",")
    .map((rule) => rule.trim())
    .filter((rule) => rule !== "");
  return rules.length === 0 || rules.includes("no-restricted-syntax");
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(?:[cm]?[jt]sx?)$/.test(entry.name) ? [path] : [];
  });
}

async function restrictedSyntaxMessages(code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, {
    filePath: `${FRONTEND_ROOT}/src/components/Probe.tsx`,
  });
  return result.messages
    .filter((message) => message.ruleId === "no-restricted-syntax")
    .map((message) => message.message);
}

describe("untyped transport lint rule", () => {
  it(
    "AC-meta.public-boundary.3 rejects every import and call of an untyped transport",
    async () => {
      for (const name of [
        "apiFetch",
        "apiStream",
        "apiUpload",
        "apiDownload",
        "apiDelete",
      ]) {
        // One finding each for the import, the direct call and the method call.
        const messages = await restrictedSyntaxMessages(
          [
            `import { ${name} } from "@/lib/api";`,
            `export const direct = () => ${name}<number>("/api/x");`,
            `export const method = (client: any) => client.${name}("/api/x");`,
            "",
          ].join("\n"),
        );
        expect(messages, name).toHaveLength(3);
      }
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "AC-meta.public-boundary.3 accepts the generated operation functions",
    async () => {
      const messages = await restrictedSyntaxMessages(
        [
          'import { apiOperation, apiOperationDownload } from "@/lib/api";',
          'export const value = () => apiOperation("list_accounts_accounts_get");',
          'export const file = () => apiOperationDownload("list_accounts_accounts_get", {});',
          "",
        ].join("\n"),
      );
      expect(messages).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );

  it("AC-meta.public-boundary.3 flags a disable directive that hides the rule", () => {
    expect(hidesTheRule(`${DIRECTIVE}-next-line`)).toBe(true);
    expect(hidesTheRule(`${DIRECTIVE}-next-line no-restricted-syntax`)).toBe(true);
    expect(hidesTheRule(`${DIRECTIVE}-line a, no-restricted-syntax -- why`)).toBe(
      true,
    );
    expect(hidesTheRule(`${DIRECTIVE} no-restricted-syntax */`)).toBe(true);
    expect(hidesTheRule(`${DIRECTIVE}-next-line no-console`)).toBe(false);
    expect(hidesTheRule(`${DIRECTIVE}-next-line react-hooks/exhaustive-deps -- x`)).toBe(
      false,
    );
    expect(hidesTheRule("const apiOperationValue = 1;")).toBe(false);
  });

  it("AC-meta.public-boundary.3 has no disable directive or ignore entry that hides the rule", () => {
    const files = sourceFiles(`${FRONTEND_ROOT}/src`);
    // A scan of an empty tree would pass; the production tree has hundreds of files.
    expect(files.length).toBeGreaterThan(100);
    const offenders = files.flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .flatMap((line, index) =>
          hidesTheRule(line) ? [`${file}:${index + 1}`] : [],
        ),
    );
    expect(offenders).toEqual([]);

    const ignored = readFileSync(`${FRONTEND_ROOT}/.eslintignore`, "utf8")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "" && !line.startsWith("#"));
    expect(ignored).toEqual(["src/lib/api-types.ts"]);
  });
});
