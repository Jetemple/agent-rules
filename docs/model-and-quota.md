# Model & quota

How aggressively to escalate model tier or reasoning effort depends on **how you pay**.

- **Plan / quota window** (e.g. "X tokens every 5 hours") — one more escalation costs zero
  dollars; the only constraint is burning the window. Escalate freely.
- **Dollar-per-token** — every escalation costs real money. Default to the cheapest capable
  model; escalate on evidence, not habit.

## The heuristic (either way)

- Start from the cheapest model/effort that can plausibly do the task well; escalate on a
  specific failure, a named risk (money, migrations, security, release), or real uncertainty
  after cheaper attempts.
- Cost is a tie-breaker only — when it ships, intelligence and taste beat cost.
- Bulk mechanical work → cheap/fast model. User-facing work (UI, copy, API design) → a model
  with good taste. Reviews → a second, more capable model as an independent perspective.

State the model, effort, and concrete reason before an expensive escalation, so the choice is
auditable rather than reflexive.
