# Operational runbooks

## Research failures

Keep failed/cancelled/timed-out attempts and audit. The trusted worker retries controller errors
with backoff; expired leases fail, not silently rerun. One linked infrastructure retry consumes quota.
Unknown costs/calendar/data quality block economic promotion. Restore DB with online backup plus
artifacts/data and external audit anchor; replay the pinned source/environment before resuming.

## Demo entry and restart

Owner starts only a broker-validated, pinned demo deployment with verified contract/cost/session
and separate state. The single-writer file lock prevents another runner on the same DB. On restart,
reconcile all intents, orders and positions before new entries. Same client intent never resubmits.
Unknown intent, unexpected/manual position, stale quote, wrong account, contract drift or missing
cash-flow history freezes entries and records a durable audit event.

## Partial fill, rejection and lost reply

Record acceptance separately from fill. Cancel and verify any remainder. On transport uncertainty,
keep the prepared intent and resolve through broker history; do not send a replacement. Explicit
rejection may free capacity. Absence from one query is not proof of rejection. Human resolution is
required if the adapter cannot prove the terminal outcome.

## Protection and loss stops

Missing/widened protection pauses and attempts to flatten the known position. If closure cannot be
confirmed, keep paused, preserve evidence and escalate to owner through the broker terminal. Daily
loss uses day-start equity including unrealized PnL and cash-flow adjustments. Drawdown high-water
and halt survive restart; no automatic reset of permanent drawdown halts. Clock regression fails.

The watchdog flattens known positions/pending orders at configured cutoff or risk halt. Broker
closure/disconnect can prevent this; entries remain paused and positions stay visible until actual
fills are confirmed. A native broker stop is required. Nobody can guarantee gap losses stop at the
planned percentage. Test this runbook against the chosen demo broker before enabling it.

## Pause, kill and rollback

Owner pause persists immediately, then optional flatten affects only owned positions. Unknown/manual
positions require owner resolution rather than discretionary liquidation. Failed flatten persists
pause and an audit event. Revoke broker/bridge access to prevent new entries if the runner is lost;
inspect actual broker positions independently because revocation does not close existing exposure.

Rollback pins a known-good artifact/policy after reconciling existing exposure; never edit an active
strategy in place or reset the risk DB. An identity mismatch requires owner intervention. No live
service is enabled; future live rollback follows authenticated deployment authorization separately.
