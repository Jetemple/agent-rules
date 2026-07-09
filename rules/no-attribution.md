# Rule: no AI attribution

Never add AI/tool attribution to anything — commits, branches, PRs, tags, docs, comments, or
any other artifact.

- No "Generated with ..." / "Co-Authored-By: ..." footers or trailers in commit messages.
- No AI/tool tokens (`claude`, `codex`, `ai`, `bot`, `gpt`, etc.) in branch names, commit
  messages, PR titles/bodies, tags, or docs.
- Keep commit messages and PR descriptions written as if the user authored them, in their voice.

If a throwaway/tooling branch name leaked a tool token, rename it before pushing:
`git branch -m old-name clean-name`, push the clean name, and delete the old one on the remote.
