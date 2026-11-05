# Implementation status

Engineering progress and strategy evidence are tracked separately. No real market data or broker
credentials have been supplied. Native MQL5 export is not implemented. No profitability claim is made.

- F0: typed frozen contracts, research-only CLI, resource preflight and CI implemented; offline checks pass. Initial SQLite schema/audit migration, safe structured logging and protocol delivered; experiment schema extends it in F2.
- F1: CSV/QA/immutable Parquet, causal seeds and cost-aware M1 backtest implemented; synthetic tests/replay pass. Real-data readiness remains blocked.
- F2–F6: pending.

Each phase is an unmerged stacked PR. Review quota: at most two Lab / Claude Opus 5.5 medium rounds
per PR. Review findings and responses are recorded under docs/reviews/.

Reviewer thread reused for all subsequent PRs: t3-thread://v1/mcp:5bf216ef-394d-4905-8372-05c8140b8300 (owner instruction, cache reuse).
