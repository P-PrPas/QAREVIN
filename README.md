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
