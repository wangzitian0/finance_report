import { createRequire } from "node:module";
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
});
