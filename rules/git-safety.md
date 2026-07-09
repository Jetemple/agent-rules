# Rule: git safety (confirm before remote writes)

Confirm before any commit, push, merge, or PR mutation. Prepare and verify locally, then get
explicit confirmation immediately before the mutating command — after the repo, branch, action,
and intended diff are all known.

A bare "OK to push?" does not satisfy this. Present the specifics so the human is confirming a
concrete action, not a blank one:

```
- Repo:          <name>
- Branch:        <branch>
- Action:        commit / push / merge / PR update
- Intended diff: <files or a one-line summary>
- Exact command: <the command you will run>
```

## What requires confirmation
- Any `git commit`, including doc-only or cleanup commits.
- Any `git push`, including to ordinary feature/PR branches, and any `--force` / `--force-with-lease`.
- Any merge, or any API/tool action that creates, updates, resolves, merges, or otherwise
  mutates a PR or branch.
- Any direct push to a protected base branch.

## What is NOT confirmation
A broad work request — "fix it", "go ahead", "ship it", "address the comments", "deploy this" —
is **not** approval for a specific commit/push/merge. Approval in one context does not carry to
the next. The confirmation must happen immediately before the mutation, with the diff and target
branch known.

## Review mode
If asked to review, explain, inspect, or sanity-check pending changes, you are in review mode.
Answer the question; do **not** resume committing or pushing afterward without a fresh explicit
confirmation for that exact action.

## If the target is uncertain
Stop and resolve the target first. Never map a service/repo by guess or naming lineage alone.
If there is any doubt, do not mutate the remote — ask.
