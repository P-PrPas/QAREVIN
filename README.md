# QAREVIN

Quantitative Adaptive Research, Evidence, Validation & Iteration Network — Hermes agent สำหรับวิจัย พัฒนา และประเมินกลยุทธ์ XAUUSD อย่างทำซ้ำและตรวจสอบหลักฐานได้

- [แผนพัฒนาและเกณฑ์ตรวจรับ](docs/DEVELOPMENT_PLAN.md) — ขอบเขต สถาปัตยกรรม F0–F6, work packages, test plan และ dependencies
- [Implementation specification v1.0](Hermes_Quant_Trading_Agent_Implementation_Spec.md) — เอกสารตั้งต้น

สถานะปัจจุบัน: กำลังพัฒนา offline research core; ยังไม่มี market-data validation หรือผล performance

เส้นทางพัฒนา: offline research → deterministic evaluation → Hermes research loop → demo forward evidence → owner-approved live ภายหลัง โดยไม่มีการอนุญาต live อัตโนมัติ

เริ่มตามแผนด้วย foundation และ CSV pipeline ภายใน directory นี้ รายละเอียด native MQL5 EA ยังเป็น decision แยกจาก Python runner ตามสเปก

## Development

Python 3.12+ (local validation: 3.14). The pinned NumPy requires 3.12; this is within the
specification's 3.11+ range. CI checks 3.12 and 3.14.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/qarevin config-check config/research.example.json
.venv/bin/qarevin preflight --job-memory-mib 768
```

The example contract, session and costs are synthetic and block demo readiness.
Preflight exit 2 means insufficient headroom: defer the job rather than change other agents.
Implementation status: [engineering and evidence](docs/IMPLEMENTATION_STATUS.md).

## Offline data and backtests

```bash
.venv/bin/python scripts/synthetic_csv.py /tmp/qarevin-synthetic.csv --days 30
.venv/bin/qarevin import /tmp/qarevin-synthetic.csv --store /tmp/qarevin-data --timezone UTC --provider synthetic --symbol XAUUSD_SYNTHETIC
# Use the dataset ID returned by import:
.venv/bin/qarevin data-qa /tmp/qarevin-data/DATASET_ID
.venv/bin/qarevin backtest /tmp/qarevin-data/DATASET_ID --config config/research.example.json --family trend --output /tmp/qarevin-results
.venv/bin/qarevin report /tmp/qarevin-results/ARTIFACT_HASH.json
.venv/bin/qarevin replay /tmp/qarevin-results/ARTIFACT_HASH.json /tmp/qarevin-data/DATASET_ID --config config/research.example.json
```

Import defaults to rejecting any row on/after 2025-01-01; keep holdout in a separate owner-only
store. Source timezone is mandatory; ambiguous DST, duplicate/conflicting/invalid bars fail the
whole atomic import. QA labels calendar gaps and bid-price basis as unverified. Incomplete
M15/M30/H1 buckets are never used for signals. Never treat synthetic results as market evidence.

Seeds: trend EMA50/200 H1 crossover, BB20/2 RSI14 mean reversion M15 with ADX14≤25 filter,
Donchian20 M30 with ATR14≥prior100 median. ATR/RSI/ADX use SMA-seeded Wilder smoothing; EMA
uses SMA initialization; Bollinger uses population standard deviation. Rules match the proposals
in the plan, not tuned parameters. The runner uses M1 bid OHLC + spread proxy, next-event entry,
adverse stop gaps, costs, lot steps, persistent per-run daily/drawdown halts and session cutoff.
No take-profit limit fills or overnight swap model are implemented; strategies exit by closed-bar
signals, stops or cutoff. Daily cutoff failures are closed at the next executable event.

Broker CSV time can be explicit `UTC+02:00`/`UTC-05:00` or `NY+07:00` (broker clock is New York
local time plus 7 hours, following US DST). This mapping is a declared data-source convention,
not an auto-detection. `stop_distance_min` is in absolute price units; MT5 points must be converted
by the adapter. Margin usage is capped at 25% of equity by default. Missing-minute exits execute
at the next available quote; entries expire when the immediate execution event is absent.
Spread used is `max(bar_spread, model_floor) * spread_multiplier`, preventing CSV spread from
bypassing conservative assumptions or stress tests. Results contain lot-fill/skip counts.
Equity is summarized hourly while retaining M1 adverse marks, peaks, margin and open risk.

## Evidence and validation

```bash
.venv/bin/qarevin experiment /tmp/qarevin-data/DATASET_ID --config config/research.example.json --family trend --hypothesis 'EMA crossover baseline after declared costs' --state /tmp/qarevin-state
.venv/bin/qarevin evaluate /tmp/qarevin-state/artifacts/results/ARTIFACT_HASH.json --config config/research.example.json
.venv/bin/qarevin replay-experiment /tmp/qarevin-state/artifacts/results/ARTIFACT_HASH.json /tmp/qarevin-data/DATASET_ID
.venv/bin/qarevin walk-forward /tmp/qarevin-data/DATASET_ID --config config/research.example.json --protocol config/walkforward.synthetic.json --output /tmp/qarevin-wf
.venv/bin/qarevin backup /tmp/qarevin-state/registry.sqlite /tmp/qarevin-backup.sqlite
```

Experiments preregister hypothesis/strategy/data/config identities and archive source before running.
Results and failed attempts remain in SQLite's immutable evidence objects and chained audit. Restore
requires BOTH the SQLite online backup and the artifacts/data stores; source archives record package
versions, and replay requires restoring the recorded source/environment. Backup is not a full-host
snapshot. Source/config/data changes cause replay to fail clearly.

Walk-forward selects candidates from validation only and evaluates non-overlapping outer tests.
Every candidate/fold attempt is counted. Stitched equity rebases **independent fold accounts**; it is
a diagnostic, not a claim of continuously deployed portfolio risk. `robustness.campaign` holds the
target fixed and evaluates stressed costs plus two preregistered neighbors. Promotion stays false
until separate sealed/future evidence exists. No-trade/no-loss/short-window metrics return null
with reasons; a single backtest can never satisfy walk-forward/robustness gates.

HoldoutService is owner-only and never exposed through agent tools. It requires disjoint owner and
research roots, freezes code/config/strategy and consumes the campaign before loading data. A crash
also consumes the opening. ResearchCatalog enforces the date boundary and dataset IDs, not file paths.
Actual deployment must mount only the research root into API/worker, never the owner holdout root.
