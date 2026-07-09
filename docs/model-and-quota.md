# Model & quota

How aggressively to reach for a bigger model or higher reasoning effort depends on **how you
pay**. The two billing shapes call for opposite defaults.

## Plan / quota-window usage

A subscription gives you a rolling token/quota window (e.g. "X tokens every 5 hours"). The
marginal cost of one more escalation is zero dollars — the only question is *"am I burning my
window?"* Within the window you can escalate model tier and reasoning effort more freely; the
constraint is throughput over the window, not cost per call.

## Dollar-per-token usage

Pay-as-you-go bills every token. Each escalation costs real money, so default to the
**cheapest capable model** and escalate on evidence — a concrete quality gap, a named risk, or
high stakes — not as a habit.

## The heuristic (either way)

- Start from the cheapest model/effort that can plausibly do the task well.
- Escalate on evidence: a specific failure, a named risk (money, migrations, security,
  cross-service contracts, release/deploy), or after cheaper attempts left real uncertainty.
- Cost is a tie-breaker only. When it ships and axes conflict, intelligence and taste beat cost.
- Bulk mechanical work (clear specs, migrations, data munging) → cheap/fast model.
- Anything user-facing (UI, copy, API design) needs a model with good taste.
- Reviews of plans/implementations benefit from a second, more capable model as an independent
  perspective.

State the model, effort, and the concrete reason before an expensive escalation, so the choice
is auditable rather than reflexive.
