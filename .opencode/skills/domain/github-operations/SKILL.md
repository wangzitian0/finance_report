---
name: github-operations
description: GitHub API operations via `gh` CLI — PR reviews, CI debugging, GraphQL mutations. Use when resolving review threads, querying PR status, fetching CI logs, or automating GitHub workflows.
---

# GitHub Operations

> GitHub API operations for PR review management, CI debugging, and workflow automation.

## Tool Priority

1. **`gh` CLI** — Primary interface for all GitHub operations
2. **GraphQL API** — For operations not available via REST (review threads)
3. **REST API** — Fallback for simple queries

---

## PR Review Threads

### Query All Threads on a PR

```bash
gh api graphql -f query='
query {
  repository(owner: "wangzitian0", name: "finance_report") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(last: 50) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 3) {
            nodes { id path body }
          }
        }
      }
    }
  }
}'
```

### Resolve a Review Thread

```bash
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "PRRT_xxx"}) {
    thread { id isResolved }
  }
}'
```

### Unresolve a Review Thread

```bash
gh api graphql -f query='
mutation {
  unresolveReviewThread(input: {threadId: "PRRT_xxx"}) {
    thread { id isResolved }
  }
}'
```

### ID Conventions

| Prefix | Entity | Used For |
|--------|--------|----------|
| `PRRT_` | Review Thread | `resolveReviewThread` / `unresolveReviewThread` mutations |
| `PRRC_` | Review Comment | Individual comment within a thread |
| `PRR_` | Pull Request Review | The overall review (APPROVE/REQUEST_CHANGES/COMMENT) |

**Pitfall**: Thread operations require `PRRT_*` IDs, not `PRRC_*` comment IDs. Using comment IDs in thread mutations will fail silently or error.

---

## CI Debugging

### List Recent CI Runs

```bash
gh run list --repo wangzitian0/finance_report -b BRANCH_NAME -L 5
```

### View Failed Run Logs

```bash
# Get the run ID from `gh run list`, then:
gh run view RUN_ID --log-failed
```

### Watch a Running CI

```bash
gh run watch RUN_ID
```

### Re-run Failed Jobs

```bash
gh run rerun RUN_ID --failed
```

---

## PR Operations

### Create PR

```bash
gh pr create --title "title" --body "$(cat <<'EOF'
## Summary
- Change description
EOF
)"
```

### Check PR Status

```bash
gh pr view PR_NUMBER --json state,statusCheckRollup,reviews
```

### Merge PR

```bash
gh pr merge PR_NUMBER --squash --delete-branch
```

---

## Common Patterns

### Batch-Resolve All Threads

```bash
# 1. Get all unresolved thread IDs
THREADS=$(gh api graphql -f query='query {
  repository(owner: "wangzitian0", name: "finance_report") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(last: 50) {
        nodes { id isResolved }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id')

# 2. Resolve each
for tid in $THREADS; do
  gh api graphql -f query="mutation { resolveReviewThread(input: {threadId: \"$tid\"}) { thread { id isResolved } } }"
done
```

### Get CI Failure Details

```bash
# List runs → find failed → get logs
RUN_ID=$(gh run list -b BRANCH --json databaseId,conclusion -q '.[] | select(.conclusion == "failure") | .databaseId' | head -1)
gh run view "$RUN_ID" --log-failed 2>&1 | grep -A 5 "FAILED\|Error\|assert"
```

---

## Source Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | CI pipeline definition |
| `.github/workflows/pr-test-env.yml` | PR test environment deployment |
| `.github/workflows/deploy-staging.yml` | Staging deployment |
