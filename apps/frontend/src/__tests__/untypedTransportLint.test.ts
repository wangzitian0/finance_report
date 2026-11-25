import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { expect, it } from "vitest";
const ROOT = process.cwd(),
  { ESLint } = createRequire(`${ROOT}/package.json`)("eslint") as {
    ESLint: new (o: { cwd: string }) => {
      lintText(
        c: string,
        o: { filePath: string },
      ): Promise<{ messages: { ruleId: string | null; message: string }[] }[]>;
    };
  },
  eslint = new ESLint({ cwd: ROOT });
const DIR = ["eslint", "disable"].join("-"),
  DIR_RE = new RegExp(`${DIR}(?:-next-line|-line)?\\b(.*)$`);
const hidesRule = (l: string) => {
  const m = DIR_RE.exec(l);
  if (!m) return false;
  const r = m[1]
    .split("--")[0]
    .replace(/\*\/.*$/, "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  return r.length === 0 || r.includes("no-restricted-syntax");
};
const walk = (d: string): string[] =>
  readdirSync(d, { withFileTypes: true }).flatMap((e) => {
    const p = join(d, e.name);
    return e.isDirectory()
      ? walk(p)
      : /\.(?:[cm]?[jt]sx?)$/.test(e.name)
        ? [p]
        : [];
  });
const lint = async (c: string) =>
  (
    await eslint.lintText(c, { filePath: `${ROOT}/src/components/Probe.tsx` })
  )[0].messages
    .filter((m) => m.ruleId === "no-restricted-syntax")
    .map((m) => m.message);
it("AC-meta.public-boundary.3 untyped transport lint", async () => {
  for (const n of [
    "apiFetch",
    "apiStream",
    "apiUpload",
    "apiDownload",
    "apiDelete",
  ])
    expect(
      await lint(
        `import { ${n} } from "@/lib/api";\nexport const d = () => ${n}<number>("/api/x");\nexport const m = (c: any) => c.${n}("/api/x");\n`,
      ),
      n,
    ).toHaveLength(3);
  expect(
    await lint(
      'import { apiOperation, apiOperationDownload } from "@/lib/api";\nexport const v = () => apiOperation("list_accounts_accounts_get");\nexport const f = () => apiOperationDownload("list_accounts_accounts_get", {});\n',
    ),
  ).toEqual([]);
  for (const [l, exp] of [
    [`${DIR}-next-line`, true],
    [`${DIR}-next-line no-restricted-syntax`, true],
    [`${DIR}-line a, no-restricted-syntax -- why`, true],
    [`${DIR} no-restricted-syntax */`, true],
    [`${DIR}-next-line no-console`, false],
    [`${DIR}-next-line react-hooks/exhaustive-deps -- x`, false],
    ["const apiOperationValue = 1;", false],
  ] as const)
    expect(hidesRule(l)).toBe(exp);
  const files = walk(`${ROOT}/src`);
  expect(files.length).toBeGreaterThan(100);
  expect(
    files.flatMap((f) =>
      readFileSync(f, "utf8")
        .split("\n")
        .flatMap((l, i) => (hidesRule(l) ? [`${f}:${i + 1}`] : [])),
    ),
  ).toEqual([]);
  expect(
    readFileSync(`${ROOT}/.eslintignore`, "utf8")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#")),
  ).toEqual(["src/lib/api-types.ts"]);
}, 30_000);
