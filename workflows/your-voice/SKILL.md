---
name: your-voice
description: Use when creating or updating a reusable writing voice profile for drafting commit messages, PR descriptions, documentation, or chat in a user's established style.
---

# your-voice

Interview yourself into a reusable "voice profile" so an agent can draft in YOUR voice
(commit messages, PR descriptions, docs, Slack). This skill helps you BUILD your own profile —
it ships no one else's voice.

## Privacy (non-negotiable)
- The generated profile is **personal** and must **never** be committed to this public repo.
- Write it OUTSIDE the repo (e.g. `~/.config/your-voice/profile.md`), NOT to a gitignored
  path inside the repo (a gitignored file can still be force-added).
- The profile file must carry the sentinel line `AGENT-RULES-PRIVATE-VOICE-PROFILE` so the
  release gate rejects it if it ever lands in a repo tree.

## Interview (ask one at a time)
1. Paste 3–5 samples of your writing you're happy with. What do they have in common?
2. Tone dial: terse ↔ warm? formal ↔ casual? dry ↔ playful?
3. Structure habits: bullets vs prose? headers? how you open and close.
4. Signature moves: phrases you use, punctuation quirks, emoji/none.
5. Hard "don'ts": words, tones, or formats you never want.
6. Context variants: does your voice change for commits vs PRs vs Slack vs docs?

## Generate
Synthesize the answers into a profile using `template.md` as the shape. Fill each section from
the interview. Write the result to the OUTSIDE-repo path above, prepended with the sentinel
line. Confirm the path back to the user; never echo it into repo files.
