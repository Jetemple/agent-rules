---
name: decision-to-plan
description: Use when the user hands over a decision (a chat, meeting notes, a pasted thread, a design discussion) and wants it turned into work other people can pick up, such as "turn this into a tech plan", "write tickets from this", "make a rollout plan", "what's still open here?", or "make this easy for the team to run with".
argument-hint: "Paste the decision, or point at the notes or thread"
---

# Decision to plan

Turn a decision someone has already made into a package a teammate can run without the author in the room. The deliverable is something others can read and act on. It is not a show of thorough thinking.

You write down the decision. You don't make it. If the input doesn't contain a decision yet, say so and stop. Do not pick one.

## Inputs

Work only from what the user gave you plus files or links they point you at. Before you write anything, check that you have each of these. If one is missing, ask for it in one message that lists every gap:

| Need | Why |
|---|---|
| The problem, and who has it | The plan opens with it |
| The decision, in one sentence | Everything else follows from it |
| Options considered and why they lost | Readers ask "why not X?" first |
| Systems, services, or code touched | Tickets and dependencies come from this |
| Constraints: deadline, compliance, budget, freeze windows | Shape the rollout |
| Who owns what | Open questions need owners |

If the user says "just draft it", go ahead. Mark every gap `TBD (ask: <who or what>)`. Never fill a gap with a plausible guess.

## Labeling rules

- Tag anything you inferred rather than read in the input: `(inferred)`. Example: a migration step the notes imply but never state.
- Quote numbers, dates and names exactly as the input gives them. Don't round them or estimate new ones.
- Sizes are relative (S, M, L) unless the team's own scale is given.
- Plain words, short sentences, no em dashes. Use a table wherever a reader would otherwise scan prose for one fact.
- Write for a reader who missed the meeting: someone new to the team, or the on-call engineer six months from now.

## Output, in this order

### 1. Tech plan (one page)

```
# <Title: the change, not the project codename>
Status: Draft | Decided | In progress    Owner: <name or TBD>    Date: <YYYY-MM-DD>

## Problem
2-4 sentences. Who is affected, what it costs today, how we know.

## Decision
One sentence, then 2-3 bullets of what it means in practice.

## Alternatives rejected
| Option | Why not |

## Design
The smallest description that lets an engineer start: components, flow, and what changes
where. A diagram only if it saves words.

## Data and API changes
| Change | Where | Backward compatible? | Notes |
Schema, contract, config, event shape. "None" is a valid answer; say it.

## Out of scope
What a reader might assume is included but isn't.
```

The plan has to fit on one page. Push detail down into tickets.

### 2. Tickets

| # | Title | Acceptance criteria | Size | Depends on |
|---|---|---|---|---|

- Each ticket can be merged and verified on its own.
- Acceptance criteria are checkable statements. "Works correctly" doesn't count.
- Order the tickets so the first one can start today.
- Where the team uses a template or tracker fields, offer the tickets in that shape after the table.

### 3. Test plan

| Acceptance criterion (ticket #) | Test | Level (unit / integration / e2e / manual) | Exists already? |
|---|---|---|---|

Every acceptance criterion maps to at least one test. Flag criteria that can only be checked in production, and say how they will be watched.

### 4. Rollout and launch checklist

A plan that explains how to build the change but not how to launch it is half done. Cover each row, or write "n/a" and give a reason:

| Item | Plan |
|---|---|
| Sequencing | What ships first. Which steps must happen before launch, at launch, or after it (for example, a column added early vs. at cutover) |
| Feature flags / audience limiting | Flag name, default state, who sees it first |
| Where it's tested first | Environment, internal users, or a percentage, and what "good" looks like there |
| Migration / backfill | Steps, how long they take, whether it needs downtime, and whether they can be rerun |
| Monitoring | Metrics, dashboards, alerts that show it's working or broken |
| Rollback | The exact steps, what can't be undone, and who decides |
| Dependencies outside this code | Other teams, vendors, config, approvals |
| Comms | Who needs to know, before and after launch, and through which channel |

### 5. Open questions and unresolved dependencies

| Question or dependency | Blocks (ticket # or "launch") | Owner | Needed by |
|---|---|---|---|

Everything marked `TBD` or `(inferred)` above lands here, so the open work all sits in one place. If the owner is unknown, write `Owner: ?`. Don't assign one.

## Before handing it back

- Read the plan as the newest person on the team would. Rewrite any sentence that needs context they don't have.
- Check that every ticket traces to the decision, and every acceptance criterion has a test.
- Lead with a three-line summary for the user: what the plan covers, how many open questions there are, and the single biggest risk.
- Don't post, file, or send anything (tickets, docs, messages) unless the user asks. Hand back the text.
