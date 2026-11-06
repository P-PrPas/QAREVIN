# Validation protocol v1 — engineering baseline

Synthetic fixtures are engine checks, never economic evidence. Signals use closed bars and execute
at the next executable event. Incomplete bars cannot produce signals. Price basis, timezone,
contract and costs must be explicit; unverified values block demo. Only parameterized trusted
seeds can run; arbitrary source execution is disabled pending an isolation gate.

Development/secondary/holdout boundaries are preregistered in immutable manifests before tuning.
Holdout is outside the research store and inaccessible to the agent. Every attempt, including
failure, counts. F2 adds independently calculated metrics and gates; no candidate can promote
before those gates exist. Unknown metrics are null with a reason, never an infinite reward.

Risk defaults are 0.25%/trade, 1% daily equity loss and 5% equity drawdown for demo. These are limits
on planned risk, not a guarantee against price gaps. Only an authenticated owner can change policy.
Live has no enabled service or credentials. A future approval workflow will bind exact artifact,
policy, account and capital identities; natural-language approval in agent output is insufficient.
