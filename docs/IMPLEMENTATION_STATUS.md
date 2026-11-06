# Implementation status

Engineering progress and strategy evidence are tracked separately. No real market data or broker
credentials have been supplied. Native MQL5 export is not implemented. No profitability claim is made.

- F0: typed frozen contracts, research-only CLI, resource preflight and CI implemented; offline checks pass. Initial SQLite schema/audit migration, safe structured logging and protocol delivered; experiment schema extends it in F2.
- F1: CSV/QA/immutable Parquet, causal seeds and cost-aware M1 backtest implemented; synthetic tests/replay pass. Real-data readiness remains blocked.
- F2: independent metrics/gates, walk-forward, fixed-artifact robustness campaigns, immutable registry/audit, source archives/replay and owner-only one-opening holdout implemented with offline tests. Real-data/holdout isolation deployment and economic evidence remain unverified.
- F3: scoped authenticated API/MCP, durable jobs/budgets/dedup, bounded parameter workers, memory/lineage, isolated profile/Compose and prompts implemented. 20 deterministic worker cycles and MCP handshake tested. Actual Hermes model/injection/budget evaluation and generated-code sandbox remain pending; no scheduled deployment.
- F4 core: demo-only pinned signal/risk/order controller, persistent reconciliation/limits, fault adapter and HTTPS bridge client contract implemented/tested. Actual broker bridge server/selected-broker acceptance remain pending (F4A); no real forward data (F4B).
- F5–F6: pending.

Each phase is an unmerged stacked PR. Review quota: at most two Lab / Claude Opus 5.5 medium rounds
per PR. Review findings and responses are recorded under docs/reviews/.

Reviewer thread reused for all subsequent PRs: t3-thread://v1/mcp:5bf216ef-394d-4905-8372-05c8140b8300 (owner instruction, cache reuse).

F1 data-readiness gaps: quarantine rejects the complete file with hash/error type, rather than
emitting per-row repair suggestions. Calendar gaps cannot be classified until the real broker
calendar is supplied; spike flags are diagnostics (5% bar-close threshold), not market validation.
Spread stress applies to risk entry limits as well as costs and can change the executed trade set.
