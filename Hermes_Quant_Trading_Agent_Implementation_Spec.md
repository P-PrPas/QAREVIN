# Hermes Quant Trading Agent — Implementation Specification

**Version:** 1.0 (design baseline)  
**Date:** 2026-11-05  
**Status:** Ready for engineering planning; not evidence of profitable performance  
**Primary objective:** Develop and evaluate adaptive algorithmic trading strategies for gold (XAUUSD), prioritizing *reproducible, risk-controlled net profitability on unseen data*.  
**Target deployment:** Ubuntu Server home lab (8 GB RAM, no GPU), Hermes Agent orchestrator, MetaTrader 5 (MT5) via broker adapter.  
**Initial mode:** Research + historical backtests + demo forward trading. **No live trading without explicit owner approval.**

---

## 1. Executive overview

Agent name: QAREVIN - Quantitative Adaptive Research, Evidence, Validation & Iteration Network

The project uses **Hermes as an autonomous quantitative research supervisor**, *not* a free-form LLM that submits buy/sell orders. The agent proposes hypotheses, changes strategy code or parameters, requests deterministic experiments, critiques the evidence, and records lessons. A separate execution service runs *approved, version-pinned* strategy artifacts. An independent risk engine constrains the order flow. Keep the three environments isolated: **research**, **demo**, **live**.

The intended learning loop is **RL-inspired feedback + memory-guided search**, not actual policy-gradient or Q-learning by default. Reward scores guide the next research action; they do not guarantee improving performance. Profitability must be demonstrated independently on unseen periods and forward performance after all costs.

### Decisions already agreed

| Subject | Decision |
|---|---|
| Instrument | Gold, XAUUSD (broker-specific symbol mapping supported) |
| Execution style | Intraday first; no new overnight holdings by default |
| Starting strategies | Three prebuilt families: trend following, mean reversion, volatility breakout |
| Agent autonomy | Automatically explore, code, tune, test, interpret, and store results in sandbox |
| Deployment path | Historical research → protected holdout → demo forward trading → human-approved limited live rollout |
| First live access | Explicit approval with written evidence report; never automatic |
| Brokers | Broker-agnostic interface; select broker later |
| Data source | MT5 CSV exported by owner initially; automatic provider fetch later |
| History | Aim for ~2016–Oct 2026, as far as actual provider history permits |
| Compute | 8 GB RAM, CPU only; constrained worker concurrency |
| Primary evaluation | Risk-gated net returns; Calmar for eligible candidate ranking; other metrics as supporting evidence |
| Research publication | Not a priority; focus on useful trading system |

---

## 2. Scope and non-goals

### In scope
- Read and validate XAUUSD market history, maintain immutable versions.
- Evaluate and improve three initial strategy classes.
- Produce realistic event-driven backtests, rolling walk-forward tests, and sealed holdout evaluations.
- Separate backtest, out-of-sample, demo, and live performance scorecards.
- Run scheduled Hermes research cycles; preserve experiments and memory.
- Start/stop immutable strategies on demo and, **only following approval**, live.
- Broker adapters covering price/tick contracts, fees, order states, market hours, lot constraints.
- Audit trails, risk limits, alerting, rollback, emergency kill switch.

### Out of scope for v1
- Direct LLM market orders; high-frequency trading/scalping; proprietary RL model training.
- Automated broker signup/funding; automatic promotion to real money.
- Promises of recurring profits; leverage optimization by agent; strategy marketplace.
- A complicated distributed system; begin as a lightweight modular monolith.

---

## 3. Reference architecture

```text
                    OWNER / TELEGRAM / WEB UI
                     | reports / approval / kill
                     v
             +-----------------------+
             | Hermes Quant Agent    |
             | hypotheses + memory   |
             | research scheduler    |
             +------------+----------+
                          | structured tool calls ONLY
              +-----------v------------------+
              | Quant Control API             |
              | RBAC, jobs, budgets, audit    |
              +--+---------+----------+-------+
                 |         |          |
      +----------v--+  +---v-------+  +v------------------+
      | Market Data |  | Research  |  | Registry / Reports |
      | Import/QA   |  | Sandbox   |  | SQLite + artifacts |
      +------+------+  +----+------+  +----------+---------+
             |               |                    |
             +------------+--v--------------------+
                          | approved strategy artifact
                +---------v------------+
                | Deployment Controller|
                | hard-coded gates     |
                +------+---------------+
                       |             |
                  DEMO broker      LIVE broker
                  adapter           adapter
                       |             ^
               +-------v-------------+-------+
               | Independent Risk Engine     |
               | order checks + circuit stops|
               +-----------------------------+
```

**Important:** Risk engine enforces checks on **every** intended trade; physical design may place the risk engine directly in the order path *before* each broker adapter. Research and execution run as separate processes/containers, and **research has no live credentials or broker order endpoint**.

### Responsibilities
1. **Hermes:** Explore hypotheses, edit draft strategy code, interpret diagnostics, manage research memory, request tools. Cannot self-approve risk limit changes or live deployment.
2. **Market Data Service:** Imports CSV or licensed API data, normalizes timezones, validates candles, stores data version/metadata and broker specifications.
3. **Research Worker:** Deterministic evaluation from strategy artifact + dataset + configuration + seed; CPU/memory/time limits; no sensitive credentials.
4. **Evaluation Engine:** Independent metrics, risk gate checks, anti-overfit checks, immutable scorecards.
5. **Strategy Registry:** Unique immutable artifact hashes, lineage, status, deployment version, experiment links.
6. **Deployment Controller:** Separate demo/live environments, user authorization checks, staged rollout and rollback.
7. **Execution Adapter:** Converts normalized signals to broker orders and reconciles positions/fills, never relies on Hermes interpreting order results.
8. **Monitoring and Audit:** Heartbeats, spread/slippage, outages, PnL, daily reports, approvals and emergency actions.

---

## 4. Proposed minimal technology stack

- **Python 3.11+**, `pandas`, `numpy`, `pydantic`, `FastAPI`, `SQLAlchemy`, `pytest`, `pyarrow`, `duckdb` (optional for analytics).
- **SQLite** for v1 registry + execution event metadata; **Parquet** partitioned by instrument/timeframe/year for candle data and result artifacts. Use WAL, backups and a single serialized write path. PostgreSQL later if concurrency requires it.
- **Docker Compose** for API, worker, scheduler, and (separately) demo/live runner. Avoid heavy k8s/Redis at first; use DB job table and worker polling.
- **Hermes Tools / Skills:** Thin HTTP/CLI wrappers over validated, versioned control API. No free-form shell access to real-money infrastructure.
- **MT5 integration:** MT5 Python package typically depends on a running terminal on supported Windows environments; do **not** assume it will natively work on headless Ubuntu. Choose either (a) Windows MT5 terminal/bridge exposed over a tightly secured private network, (b) carefully tested Wine container/VM, or (c) broker-supported API with independent adapter. Confirm deployment mechanism before implementation. Research/backtests work directly on Ubuntu without terminal.
- **Security:** Separate credentials per environment, secrets via Docker secrets or OS-protected secret store, private network/Tailscale, TLS/auth, no public unauthenticated order endpoints.

### Suggested repository layout

```text
hermes-quant/
  README.md
  docs/architecture.md
  docs/runbooks.md
  config/default.yaml
  config/risk_policy.yaml          # human-managed, not agent-writable
  strategies/
    trend_ema_atr.py
    mean_reversion_bb_rsi.py
    breakout_donchian.py
  src/quant/
    api/                         # permissions, research control, approval
    data/                        # mt5 CSV import, resample, QA
    features/                    # causal indicators
    backtest/                    # event-driven engine, cost models
    evaluation/                  # metrics, walk-forward, gates
    registry/                    # strategy and experiment lifecycle
    memory/                      # structured retrieval of experiments
    broker/                      # interface, demo, MT5 bridge
    execution/                   # independent runner + reconciliation
    risk/                        # trade risk checks and circuit breakers
    reports/                     # human-readable candidate report
  workers/research_worker.py
  workers/demo_runner.py
  workers/live_runner.py
  hermes/skill.md
  hermes/tool_schemas.json
  tests/
  scripts/import_mt5_csv.py
  docker-compose.yml
```

---

## 5. Data ingestion and point-in-time correctness

### Accepted initial source
Import owner-exported MT5 CSV, ideally **M1 OHLCV** for 2016–Oct 2026 or maximum available. Export may not cover the entire requested span; record coverage honestly. Import any **tick, bid/ask, spread**, contract specs, commissions, swap, and trading sessions available. M1 OHLC does **not** recover the exact bid/ask path or realistic tick-by-tick execution.

### Required schema (normalized candles)

```text
provider_id, broker_id, symbol, timeframe, timestamp_utc,
open, high, low, close, tick_volume, real_volume,
spread_points_optional, source_file_hash, ingestion_time_utc
```

- Canonical timestamps in UTC, preserving **source timezone**, DST rules and broker server time conventions in metadata.
- Derive M15/M30/H1 **only** from timestamp-aligned lower-timeframe bars. Never roll future bars into prior indicator states.
- Check duplicates, descending timestamps, invalid OHLC, nonpositive prices, gaps, weekends/holidays, DST drift and anomalous spikes.
- Distinguish **missing data** from market closure; flag data discontinuities, do not silently fabricate price bars.
- Preserve raw file hash and a QA report; data revisions create a new `dataset_version`, not silent replacements.
- Maintain explicit provider contract specs: quote currency, tick size/value, lot size, minimum step, spread, stop level, trading schedule, margin/leverage, fees. Broker symbol may differ (`XAUUSD`, suffixes); adapters map it.
- News features optional future phase; timestamps must reflect **time available to the trader**, not article/event date only, to prevent look-ahead.

### Temporal splits and contamination policy

Suggested provisional plan:
- **2016–2022**: development and walk-forward selection (rolling train/validation windows; never fit on evaluation future).
- **2023–2024**: secondary out-of-sample evaluation / selection **if accessed repeatedly, no longer a pristine final test**.
- **2025–Oct 2026**: initial **sealed final holdout**, opened only for predetermined candidate promotions. Any repeated access drives selection bias; log every opening. Once used for feedback/iteration, mark contaminated and do not re-present it as unseen.
- **Post-launch future data**: true forward evaluation in demo and then live. This is the only way to accumulate genuinely new evidence over time.

An alternative is a **nested walk-forward** scheme with final untouched tail. Keep enough history in each regime and record change points. A single historical split is not sufficient proof of stability. Historical bars from the same source can still be biased by broker feed quirks.

---

## 6. Three seed strategies (hypotheses, not validated edges)

**General rule:** trade signals calculated on **closed candle only**, execute no earlier than next executable quote/bar; reject look-ahead and same-bar entry/exit assumptions without tick sequencing.

### S1. EMA Trend Following (H1)
- Baseline inputs: EMA(50), EMA(200), ATR(14).
- Long condition: fast EMA > slow EMA, with defined entry trigger (e.g., confirmed fast EMA crossover); short inverse. Use a strictly codified signal and baseline exit rule.
- ATR-based initial stop and position sizing; e.g., initial stop distance = `2 × ATR(14)` only as a **baseline hypothesis**.
- Risk controls and intraday close policy override entry/exit.
- Candidate research dimensions: lookback combinations, trend-strength filter, session filter, stop mechanism. Prevent large indiscriminate search grids.

### S2. Bollinger/RSI Mean Reversion (M15)
- Baseline inputs: Bollinger Bands(20, 2σ), RSI(14).
- Example long: prior completed close below lower band + RSI below configurable threshold, then reversal-confirmed entry; short mirror.
- Stop using ATR; target mean/band; disable when regime filter indicates strong trend.
- Explicitly backtest behavior during gold news spikes; mean reversion is vulnerable to prolonged directional moves.

### S3. Donchian Volatility Breakout (M30)
- Baseline inputs: Donchian Channel(20), ATR(14).
- Entry on **completed bar** breaking channel derived from *prior* 20 bars (do not include candidate bar in channel).
- ATR volatility filter, stop rules and optional time-based exit.
- Stress test opening-session gaps and high-impact news periods.

### Comparable baselines
- Original untouched code/parameters of each seed.
- **No-trade baseline**, simple buy/hold only as contextual comparator (not comparable intraday risk), and simple cost-aware random or permuted signal control for sanity.
- Every evolved strategy has `parent_strategy_id`, `change_summary`, and exact code hash.

---

## 7. Backtesting and realistic costs

Build an event-driven or carefully specified vectorized engine with deterministic fills. For intraday gold, realistic costs and intra-bar ordering matter more than shaving simulation time.

Required simulation features:
- Signal at completed candle → order sent next available execution opportunity.
- Bid/ask spread (time-varying where data permits), commission, slippage scenarios, execution delay.
- Stop/take-profit ambiguity when both occur inside one OHLC bar: use **conservative** ordering or intrabar data, never choose whichever favors strategy.
- Partial fills, minimum lot size, broker tick values, margin, rejected orders, overnight cut-off, circuit breakers.
- Latency stress tests and multiple spread/slippage assumptions.
- Exact strategy and risk configuration used in simulation matches production runner.

Do not trust profitable backtests if fill rules, transaction costs, contract sizes, or time normalization are unknown.

---

## 8. Evaluation scorecards, gates and reward

### Metrics (all separately reported)

| Metric | Definition and purpose |
|---|---|
| Net PnL | After spread, commission, slippage, financing where relevant |
| Net return / CAGR | Equity-based return; annualization only for adequate durations |
| Maximum drawdown | Largest peak-to-trough equity loss, including open risk as applicable |
| Calmar Ratio | Usually CAGR / absolute max drawdown; **unstable on short windows**, do not rank by it alone |
| Sharpe Ratio | Annualized mean excess return / volatility using consistent daily equity returns |
| Profit Factor | Gross winning trade PnL / absolute gross losing PnL; undefined if no losses |
| Trade count / exposure | Statistical adequacy; count **independent** trades, clustering caution |
| Tail risk | Worst-day loss, expected shortfall, adverse fill sensitivity |
| Stability | Across rolling windows, regimes, brokers/fees, parameter neighborhoods |
| DSR / multiple-testing control | Optional correction for trying many variants; requires appropriate assumptions and number of trials |

### Proposed **v1 experimental** gates (not scientifically universal)

**Research / walk-forward:**
- Net profitability after costs > 0.
- Max drawdown ≤ 15%.
- Profit factor > 1.2.
- Minimum 100 trades across the stated evaluation window (necessary but **not sufficient** statistical evidence).
- Walk-forward OOS net profit > 0, max drawdown ≤ 15%, and Calmar > 0.5 *when horizon long enough for interpretation*.
- Check stability across time slices and stressed cost assumptions; do not promote on single aggregate score.

**Demo forward:**
- Minimum 3 calendar months **and** enough trades/market states for informative evidence. Three months alone does not validate a strategy.
- Max risk per trade **0.25%** of demo equity (starting baseline).
- Daily cumulative loss stop **1%** of day-start equity.
- Stop/pause strategy at **5%** peak-to-trough demo drawdown.
- Demo equity default **USD 1,000** if broker supports realistic minimum lots and stop distances; if 0.25% risk ($2.50) is unachievable due to lot sizing, **skip the order**, choose a suitably sized demo setup, or revise the policy with owner consent.

**Live:**
- Requires owner-set capital amount and written live-specific risk policy, after selecting actual broker and proving order execution in demo.
- No autonomous elevation of risk, no exceeding minimum lots, no relaxing stops or limits to obtain fills.
- Initial live rollout is bounded and reversible; owner may halt at any point.

**Hard fail:** any breached risk policy, evidence of leakage, irreproducible result, inconsistent symbol/contract specs, missing audit records, or inadequate margin.

### Reward scheme (for research guidance only)

1. **Hard gates first:** candidates failing safety/data-integrity gates are `REJECTED`, regardless of return.
2. Among passing candidates, compare **walk-forward OOS** risk-adjusted outcome to the immutable baseline. A possible normalized heuristic:

```text
reward_research = improvement_in_robust_OOS_score
                  - complexity_penalty
                  - instability_penalty
                  - estimated_multiple_testing_penalty
```

`robust_OOS_score` must be precisely defined in config and invariant across an experiment batch, e.g. median return-to-drawdown across walk-forward folds, with caps when drawdown approaches zero. Avoid opaque scoring and selecting the best of thousands of trials.

3. Maintain **separate ledgers**: `in_sample_score`, `walk_forward_score`, `holdout_score`, `demo_score`, `live_score`. Never fold an unseen final holdout into the agent's iterative reward.
4. **Demo/live feedback** helps investigate regime shifts and fill discrepancies, but these regimes are not interchangeable. Small samples mean noisy scores. A worse live score may reflect overfitting **or** spread, slippage, changing regimes, operational errors or randomness. Require a diagnostic comparison rather than asserting a single cause.
5. This design is **not RL training by itself**; it is feedback-guided search orchestrated by an LLM.

---

## 9. Anti-overfitting and exploration policy

- Log *all* research attempts, including discarded ones. Do not quietly delete failed experiments.
- Pre-register hypothesis, expected effect, data span, max search budget and stopping criterion **before** running a test.
- Nested or rolling walk-forward selection, independent holdout, fixed evaluation pipeline, purged/embargoed windows when labels/holding periods overlap.
- Restrict parameter search and feature complexity; prefer stable plateaus over one exact optimum.
- Use controls: randomized/permuted signals, altered fees, day/session slices, robustness across volatility regimes.
- Monitor **research-space concentration** (many near-duplicate trials) and **lack of meaningful improvement**.
- Initial exploration budget as a *research heuristic*: 70% improving current families, 20% trying other established patterns, 10% unconventional hypotheses. Treat as **time/experiment budget**, not capital allocation, and adjust after evidence.
- Trigger exploration on stagnation (e.g., N recent failed independent experiments), but do not grant access to sealed test data.
- Keep a *frozen champion* and one or more challengers. Compare on the same future evidence windows; do not overwrite the champion in place.
- No repeated “final” testing with revisions after each result. Every use of a holdout must be recorded, and a contaminated holdout demoted to development history.

---

## 10. Hermes memory and experiment registry

**Distinction:** Agent memory stores *interpretations and hypotheses*; immutable DB and artifacts store **truth**.

### Suggested entities

```text
DatasetVersion(id, provider, span, timeframe, sha256, qa_report, created_at)
Strategy(id, family, parent_id, code_sha256, parameter_json, status)
Experiment(id, strategy_id, dataset_id, split_manifest_id, cost_model_id,
           seed, git_commit, started_at, finished_at, result_sha256,
           metrics_json, gates_json, hypothesis, notes)
Promotion(id, strategy_id, target_env, evidence_report_sha256,
          requested_at, approved_by, approved_at, expiry_at, status)
Deployment(id, strategy_id, env, broker_adapter, account_alias,
           artifact_sha256, risk_policy_sha256, started_at, stopped_at)
OrderEvent(id, deployment_id, client_order_id, broker_order_id,
           timestamp_utc, event_type, payload_sha256)
DailyEquity(id, deployment_id, date, realized_pnl, unrealized_pnl,
            equity, margin, max_intraday_drawdown)
AgentMemory(id, experiment_id, hypothesis, observation,
            alternative_explanations, recommended_next_step)
```

All results must link to exact strategy, parameters, source data, transaction-cost model, code commit, environment and seed. Never claim “learned” based on a free-form memory paragraph without experimental evidence.

Example memory:

```yaml
hypothesis: "Trend filter improves M15 mean-reversion outcomes in persistent directional regimes"
experiment_ids: ["exp_0134", "exp_0135"]
observation: "OOS drawdown reduced in 2/4 folds; aggregate return decreased"
confidence: "low"
alternative_explanations: ["smaller market exposure", "sample noise"]
next_action: "Compare equal-exposure variants with unchanged costs"
```

---

## 11. Agent skill and safe tool contracts

Expose specific tools, not unrestricted Python or shell on production services. Tool responses are strict JSON validated server-side.

| Tool | Access | Purpose |
|---|---|---|
| `market.list_datasets` | Read | Coverage, QC, provenance |
| `market.import_csv` | Owner/admin or sandbox | Import owner-supplied CSV |
| `research.propose` | Agent | Register hypothesis/branch |
| `research.run_backtest` | Agent | Queue bounded test job |
| `research.run_walk_forward` | Agent | Queue bounded validation job |
| `research.get_result` | Agent | Immutable metrics, plots, diagnostics |
| `research.compare` | Agent | Baseline/challenger and fold comparison |
| `registry.register_candidate` | Agent | Store hashed artifact, no deployment |
| `registry.get_lineage` | Agent | Avoid duplicate research loops |
| `promotion.request_demo` | Agent | Subject to gate validation |
| `promotion.request_live` | Agent | Generate report for human; **no activation** |
| `promotion.approve_live` | **Owner only**, separate identity + confirmation | Issue signed time-bound approval |
| `execution.deploy_live` | Deployment controller only | Verify signature, artifact, policy, broker, capital and environment |
| `execution.pause` | Owner / watchdog | Stop new entries; reconcile open positions |
| `execution.emergency_stop` | Owner / watchdog | Stop new entries and follow explicit flattening runbook |

**Never allow the agent's tool token to call owner-only methods**, regardless of prompt text. Treat strategy code and external news/market data as untrusted. The research worker must run in a sandbox with network and filesystem restrictions, resource/time limits, and without credentials. A strategy artifact cannot embed arbitrary network calls or execute side effects in production.

### Proposed experimental workflow

```python
while research_budget_available():
    context = read_recent_metrics_and_structured_memory()
    hypothesis = hermes_propose_testable_hypothesis(context)
    register_hypothesis_before_running(hypothesis)
    candidate = generate_candidate_in_research_sandbox(hypothesis)
    result = evaluate_backtest_and_rolling_oos(candidate, frozen_policy)
    store_immutable_artifacts_and_all_metrics(result)
    record_memory_with_alternative_explanations(result)
    if result.passes_independent_gates:
        register_candidate(result)
        # Final holdout only at controlled promotion milestone.
        # Demo may be approved via a separate guarded workflow.
```

Place hard caps (example v1): **one** CPU-intensive research worker at a time, per-job RAM ~1–2 GB, max job run time, max 20 experiments/day, max 2 concurrent API requests. Tune against actual machine headroom; shared 8 GB home lab may require much lower ceilings.

---

## 12. Broker abstraction and execution safety

### Broker adapter (pseudointerface)

```python
class BrokerAdapter:
    def get_account(self): ...
    def get_instrument_spec(self, symbol): ...
    def get_market_status(self, symbol): ...
    def get_quotes(self, symbol): ...
    def get_bars(self, symbol, timeframe, start, end): ...
    def place_order(self, order_request, client_order_id): ...
    def cancel_order(self, order_id): ...
    def modify_protection(self, position_id, stop_loss, take_profit): ...
    def get_positions(self): ...
    def get_order_status(self, client_order_id): ...
    def get_fills(self, since): ...
    def get_account_history(self, since): ...
    def health_check(self): ...
```

### Execution invariants
- Signal generation is deterministic for deployed strategy version.
- Before entry: check account identity/environment, broker session, margin, maximum spread, market freshness, lot sizing, risk budget, existing exposure, open-order state and circuit breakers.
- **Fail closed** on stale quotes, adapter disconnection, missing contract spec or risk-state uncertainty.
- Use persistent client order IDs and reconciliation on restart to prevent duplicate entries.
- Track order accepted vs actually filled, partial fills and rejected/cancelled orders separately.
- Separate `demo` and `live` accounts, credentials, deployment databases and processes; never switch by changing a single flag in the agent prompt.
- No discretionary live position changes by Hermes. When the live circuit breaker trips, trading halts; open positions follow a human-reviewed precommitted runbook, because immediate liquidation may not always be executable or optimal.
- Broker adapter contract tests must run against each broker's demo before enabling it in production.

---

## 13. Live promotion: mandatory human approval

A **candidate report** must be generated before a live request, containing:

1. Strategy name, immutable commit/hash, full human-readable logic and differences from parent.
2. Data provider, history coverage, data quality and all test split boundaries.
3. Number of variants explored, walk-forward folds, holdout access count and leakage controls.
4. Full net PnL, drawdown, Sharpe/Calmar, trade count and stressed spread/slippage analysis.
5. Demo length, trades, equity chart, live-like fill diagnostics and broker differences.
6. Reasons for confidence **and major reasons the inference might be wrong**.
7. Exact broker/account alias, initial capital, lot constraints, position limits, stop thresholds, proposed start date.
8. Rollback and kill procedure, currently deployed strategies and correlated portfolio exposure.
9. Explicit owner approval with signed, short-lived token tied to **strategy hash + risk policy hash + broker/account + notional cap**. Expired or mismatching approval is invalid.

**Absolute rule:** Hermes can *request*, but cannot *grant*, live authorization; no approval based only on natural-language messages sent by the agent. The deployment service verifies the authenticated owner action.

---

## 14. Monitoring, alerts and operational runbooks

### Observability
- Daily PnL/equity/drawdown and realized-vs-unrealized split.
- Rolling comparison: live vs demo vs matched hypothetical backtest at actual time/quotes.
- Quote staleness, spread widening, slippage, broker rejects, disconnections, out-of-sync orders.
- Strategy drift / changes in hit rate, trade distribution, volatility exposure.
- Research throughput, duplicate tests, memory retrieval quality, number of test variants.
- Resource monitoring: CPU, RAM, disk space, DB integrity and backup status.

### Alerts
- Risk limit near breach/breached; execution halted; missing stop; stale quote; order mismatch.
- Demo or live performance falls outside expected simulation range (use uncertainty intervals; avoid false alarms on a few trades).
- Critical events require notification and persistent acknowledgement log; cannot rely on a single chat delivery.

### Runbooks
- Broker disconnect: stop new entries, persist local intent, query broker state upon reconnect before any new order.
- Service restart: reconcile open orders/positions, refresh daily loss state, and revalidate risk policy.
- Unexpected position: freeze new orders, alert, resolve through owner-defined manual/automatic safety workflow.
- Faulty strategy build: immediate rollback to known-good deployment artifact; preserve full evidence.
- Kill switch: revoke/disable new order submission and follow explicit open-position policy.

---

## 15. Implementation phases and acceptance criteria

### Phase 0 — Foundation and risk charter
- Freeze initial written risk limits and owner-only change policy.
- Define instrument contract, account isolation, approval API and deployment states.
- Create project skeleton, schemas, backup/restore and secrets handling.
- **Done when:** research cannot access production credentials or owner-only endpoints, verified by automated tests.

### Phase 1 — Data and three deterministic seed strategies
- Build CSV ingestion + time normalization + QA, resampling and indicators.
- Implement seed strategies, basic event-driven fill model and synthetic test fixtures.
- **Done when:** each simulation is repeatable with identical hashes/metrics and unit tests catch indicator leakage.

### Phase 2 — Robust evaluation & registry
- Add fees, slippage stress, rolling walk-forward splits, holdout isolation, metrics and gates.
- Implement immutable experiment registry, strategy lineage and reports.
- **Done when:** complete experiment reconstructs from stored code/data/config/seed; failing cases are rejected by gates.

### Phase 3 — Hermes research loop
- Build scoped tools, skill instructions, memory retrieval, experiment caps, anti-duplication and scheduler.
- Run baseline comparisons, validate that agent never changes evaluator/risk policy.
- **Done when:** 20+ autonomous research runs produce auditable hypotheses, artifacts, comparisons and no credential boundary violations; count is engineering smoke coverage, not performance evidence.

### Phase 4 — Demo integration
- Implement one broker adapter + execution reconciliation and independent risk engine.
- Enforce 0.25%/trade, 1%/day, 5% demo drawdown, and overnight policy.
- Run extensive fault injection (disconnects, stale spreads, duplicate orders, server restarts), then demo forward test for at least 3 months and sufficient trades.
- **Done when:** risk tests pass, audit is complete, execution vs simulation discrepancies are explained, no unauthorized live actions are possible.

### Phase 5 — Live promotion workflow (disabled by default)
- Implement owner-signed approval screen, mandatory evidence report, version pinning and rollback.
- Add live broker only after demonstrated demo robustness and owner budget selection.
- **Done when:** tests show expired/altered/missing approvals cannot deploy; hard stops and reconciliation proven on selected broker.

### Phase 6 — Continuous improvement
- Run bounded research on new forward data, champion/challenger tracking, periodic reports.
- Analyze score gap causally (data drift, risk, fills, sampling) and update strategy only via a new versioned evaluation/promotion cycle.

---

## 16. Test plan: non-negotiable automated checks

**Data:** corrupt CSV, duplicate times, broker timezone DST, missing bars, nontrading-day gaps, resampling correctness.  
**Backtest:** indicators never use future values, next-bar execution, stop/take-profit collision, spread expansion, no-fill, lot sizing, leverage/margin.  
**Metrics:** drawdown on equity, annualization edge cases, no-trade division by zero, negative returns, fee sensitivity, DSR preconditions.  
**Agent:** invalid tool arguments, search budget exhausted, duplicate idea detection, memory misinterpretation, prompt injection in external data, attempts to edit risk policy.  
**Broker:** restart/reconcile, idempotent order requests, rejected order, partial fill, disconnected terminal, symbol suffix mapping.  
**Risk:** stop on daily loss or drawdown, multiple simultaneous positions, overlapping strategy risk, stale price, emergency halt and fail-closed behavior.  
**Approval:** no signature/no live access; scope mismatch/no live access; new strategy hash needs new approval; approval expires; owner can revoke.  
**Operations:** full restore from backup, backtest reproduction on clean host, crash recovery, resource limits on 8 GB machine.

---

## 17. Open decisions to resolve *at implementation*, not before architecture

- **Broker and live MT5 bridge**: choose and validate demo capability, contract specs and stable connectivity; keep all other services broker-neutral.
- **Detailed intraday window / timezone**: define session restrictions and automatic position close time, including DST handling and Friday cutoff.
- **Initial demo notional**: USD 1,000 provisional; check whether minimum lot size makes 0.25% risk executable.
- **Exact entry and exit details** for 3 seed strategies: freeze baseline strategy rules before any tuning so baseline is truly reproducible.
- **Slippage and spread sourcing**: acquire bid/ask/ticks if available; otherwise conservative scenario analysis with explicit limitation.
- **Holdout policy**: exact number of sealed test unlocks and promotion milestones.
- **Live capital and per-trade exposure**: owner decides only after demo; all live-order endpoints disabled until then.

---

## 18. Initial prompts for implementing agent

> You are implementing the Hermes Quant Trading Agent per this spec. Build a minimal, testable, auditable Python modular monolith on an 8 GB RAM, CPU-only Ubuntu Server. First implement data ingestion, deterministic backtesting, strategy registry and strict separation between research, demo, and live. Do not implement or enable live trading until isolated approval and risk-control tests pass. Treat all evaluation thresholds as configurable owner-controlled experimental defaults, not evidence of profitability. Ensure no look-ahead, no test-data contamination, no agent access to real credentials, and no missing trading-cost assumptions. Work phase-by-phase; run tests, report design deviations and unresolved broker dependencies. Do not silently relax risk or deployment gates to make tests pass.

### Recommended first PR
1. Project scaffold, config loading, strongly typed data schemas, SQLite/Parquet artifacts.
2. MT5 CSV importer + QA + M15/M30/H1 resampler + unit tests.
3. Deterministic seed strategy interfaces and closed-bar indicator functions.
4. Minimal backtest engine with cost models, equity log and reproducibility test.
5. CLI: `quant import`, `quant backtest`, `quant evaluate`, `quant report`.

### Definition of success
**Engineering success:** system is reliable, auditable and safe in demo/live boundaries.  
**Research success:** an improved strategy consistently outperforms frozen baselines on rolling OOS and future demo results *after costs*.  
**Economic success:** sustained, risk-adjusted live net profitability with explicit uncertainty and controlled drawdowns. **None of these are guaranteed by an LLM, memory, or a favorable historical score.**

---

## 19. Design rationale: common misconceptions to avoid

- **Memory ≠ learning weights:** Hermes memory can improve experiment selection and avoid repeats, but it does not automatically train a policy or confer trading edge.
- **Backtest profit ≠ forecast:** parameters selected after repeated tests are vulnerable to multiple-testing bias even if their backtest is excellent.
- **Good OOS ≠ live guarantee:** spreads, fees, actual fills, broker differences and changing market conditions can destroy a historical edge.
- **Failed live results ≠ definitely overfit:** investigate operational errors and uncertainty before attributing cause.
- **Calmar ≠ universal quality:** on short samples it can be inflated by small observed drawdown; use together with hard gates and uncertainty/stability.
- **Prompt instructions ≠ security:** risk limits and approval must be enforced in independent deterministic code and credentials/permissions.

**Final architectural principle:** *Let Hermes be creative about hypotheses, but never discretionary about risk permissions, data integrity, evaluation rules, or live execution authority.*
