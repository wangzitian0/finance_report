This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to load Space Grotesk and Fraunces.

## Architecture

The app uses a **left sidebar tabbed workspace** layout (similar to Dokploy/Arc):

- **AppShell** - Root layout wrapper with sidebar + workspace tabs
- **Sidebar** - Collapsible left navigation (256px expanded, 64px collapsed)
- **WorkspaceTabs** - Top tab bar tracking open pages (persisted to localStorage)

## Key Pages

| Route | Description |
|-------|-------------|
| `/` | Redirects to `/dashboard` |
| `/dashboard` | Financial dashboard with charts |
| `/accounts` | Chart of accounts (placeholder) |
| `/journal` | Journal entries (placeholder) |
| `/statements` | Bank statement upload (placeholder) |
| `/reports` | Reports index with Balance Sheet, Income Statement |
| `/reports/balance-sheet` | Balance sheet report |
| `/reports/income-statement` | Income statement report |
| `/reports/cash-flow` | Cash flow statement (placeholder) |
| `/reconciliation` | Reconciliation workbench UI |
| `/reconciliation/unmatched` | Unmatched transaction triage |
| `/chat` | AI Advisor chat interface |
| `/ping-pong` | API connectivity demo |

## Environment Variables

### `NEXT_PUBLIC_API_URL`

- **Rule**: Must **NOT** end with a slash `/`.
- **Reason**: The frontend client automatically appends paths starting with `/`. Double slashes (`//`) can cause 404s on some proxies.
- **Example**: `https://api.example.com` (Good), `https://api.example.com/` (Bad).

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
