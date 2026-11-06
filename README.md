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

Registered walk-forward CLI runs keep a registry beside the output artifacts; pure-library runs
without a store are unregistered diagnostics and cannot pass robustness eligibility. Every trial
and campaign is preregistered before computation, including repeated runs of the same protocol.
Holdout binds dataset/protocol as well as strategy/code/config, and a different campaign name
cannot reopen a consumed dataset. Holdout starts before 2025 are rejected.

Source archives are published atomically and verified when reused. Source-checkout experiments
require lockfile/pyproject; archives include `requirements.environment.txt` for all resolved packages.
Restore that file and the Python minor before replay; extra packages are tolerated, recorded package
version mismatches are rejected. Replay reports exact hash equality plus abs=1e-8/rel=1e-10 numeric
reproduction. Audit anchors appear in result artifacts and `.anchor.json` beside database backups;
keep them with an owner-controlled backup, since a local hash chain alone cannot prevent an
administrator from rewriting both the database and every local anchor.

The owner-configured WF registry is `--state` (default `~/.local/share/qarevin`), independent of
output location. Call `robustness.preregister_campaign` first, then `campaign` with the returned
id; a matching prior registration is mandatory and repeating a target campaign blocks eligibility.
Owner holdout preregistration requires a passing matching robustness record. Consumption is bound
to raw-file identity and overlapping UTC ranges, so dataset aliases cannot reopen the same history.
Identical registered backtests become audited replays of the original artifact.

## Hermes research integration (F3)

```bash
.venv/bin/python scripts/setup_local.py  # dedicated ignored state/data/token, starts nothing
.venv/bin/python scripts/configure_hermes.py --base ~/.hermes-trevan/config.yaml --dry-run
# Generate into a fresh home after checking the dry-run; no keys are copied:
.venv/bin/python scripts/configure_hermes.py --base ~/.hermes-trevan/config.yaml
# Import ONLY accessible research data into ./data, then check memory before starting:
.venv/bin/qarevin preflight --job-memory-mib 1024
# Optional, when headroom permits:
export QAREVIN_HERMES_HOME="$HOME/.hermes-qarevin"  # outside shared research state
docker compose up -d --build qarevin-api qarevin-worker
```

The core API binds localhost:8788, authenticates an owner-only token file, caps request size and
concurrency, and exposes only research/read/request operations. Jobs use durable leases, atomic
budgets (default 5/day), semantic deduplication, idempotency, cancellation and failed/timed-out state.
The trusted controller runs a parameter-only child with stripped environment and CPU/memory/file
limits. The Compose worker has no network and no secrets. Arbitrary Python source remains disabled;
resource limits alone are not claimed to sandbox arbitrary hostile code. Initial agent datasets
are capped at 250,000 M1 rows: partition owner inputs rather than loading all history on this host.

Agent result tools return bounded summaries, 20 recent trades and 24 equity samples rather than
entire curves. Full evidence remains immutable in the registry. The generated Hermes profile
copies only non-secret model identity settings, disables shell/file/delegation/other toolsets and
uses its own home. Configure model/Telegram secrets privately and validate actual tool inventory
on the installed Hermes version before enabling the optional `agent` profile. Pin
`QAREVIN_HERMES_IMAGE` to a tested digest; the placeholder deliberately cannot start an agent.
No existing Hermes config or container is changed by these scripts.

No scheduler or outbound chat is installed automatically. `jobs/` contains bounded research/daily
prompts for owner-installed Hermes jobs after actual-agent budget/injection evaluation. The 20-cycle
offline test uses real bounded workers with synthetic data, not an LLM. `eval/injection_cases.json`
is the corpus for the still-pending actual Hermes evaluation. API permission tests are not a
substitute for that gate. No credentials are present in the repository.

F3 review hardening: the worker retries transient controller errors with backoff, polls without a
SQLite write lock, renews its lease, and services restart unless stopped. One explicitly linked
infrastructure retry is supported by backtest tools (`retry_of`); failures still consume quota.
Hypotheses/candidates/memory/promotion creation have daily caps, and denied-request audits coalesce.
The full 24/6/6-month protocol exceeds the initial 250k row cap: agent WF is diagnostic only.
Use suitable owner-managed compute for full historical validation.

The cached Hermes digest `d4da4a40...` passed non-root/no-capabilities/no-network CLI and actual MCP
stdio handshake checks. Compose now bypasses root init and runs UID1000 with zero added caps.
This validates loading tools, not model behavior/gateway delivery. Export
`QAREVIN_HERMES_HOME="$HOME/.hermes-qarevin"` when enabling the optional agent profile. Built-in
Hermes memory is disabled; interpretations use evidence-linked Qarevin memory instead.

`QAREVIN_HERMES_HOME` is required by Compose and must be outside `QAREVIN_STATE_DIR`; this keeps
model/Telegram credentials out of API/worker mounts. The API's owner-access bridge permits outbound
networking for published-port compatibility; the worker remains without network and neither API nor
worker receives model/broker secrets. Actual API network policy should be restricted on deployment.
Permission denials, including sealed-data access, are audit-recorded with per-route coalescing.

## Demo execution safety (F4 engineering)

```bash
.venv/bin/python scripts/demo_smoke.py --output /tmp/qarevin-demo-smoke
.venv/bin/pytest tests/test_execution.py -q
```

`DemoRunner` is owner-process-only, demo-account-only and requires verified instrument/cost/session
config. It has a process file lock and thread serialization, persistent pre-send intents and cash-flow
adjusted daily/high-water risk state. Unknown replies never resubmit; restart reconciles first;
partial-fill remainders are cancelled; missing/widened stops pause and flatten known exposure.
Stale quotes, clock regression, unexpected positions, contract/account drift and unavailable margin
fail closed. The watchdog handles cutoff/risk stops. Manual positions remain for owner resolution.
`DemoStrategy` connects pinned causal seed signals to that path and rejects future bars/code drift.

The smoke command is hardwired to FakeBroker and produces **zero months of forward evidence**.
HTTPDemoAdapter defines an HTTPS/private bridge contract with explicit symbol suffix mapping, strict
responses, account/environment-bound headers, no proxy/redirect/retry behavior, and bounded bodies.
The actual MT5/broker bridge server is not implemented or validated yet: see
[bridge contract](docs/BRIDGE_CONTRACT.md) and [runbooks](docs/runbooks.md). There is no enabled
broker runner in Compose and no order tool/API for the agent. F4A broker acceptance and F4B ≥3 real
calendar months remain external gates. Static margin estimates need broker-specific validation.

## Owner authorization workflow (F5, live disabled)

`CandidateReport` pins all report/evidence hashes, actual scope/account/capital/notional cap,
research metrics and stressed costs, trial/holdout counts, demo dates/trades/drawdown/risk incidents,
rollback and uncertainty. Readiness checks require verified non-synthetic evidence, adequate
research metrics, ≥3 calendar months and ≥100 demo trades. These fields are owner attestations
assembled from immutable evidence; the schema/signature itself is not proof the assertions are true.

```bash
# Optional owner workstation preparation, outside repo/research/agent mounts:
.venv/bin/python scripts/owner_approval.py keygen --directory "$HOME/.config/qarevin-owner/keys"
# Only a content-addressed candidate packet with all real gates passed can be signed:
.venv/bin/python scripts/owner_approval.py sign --packet /OWNER_REPORTS/HASH.json --state "$HOME/.config/qarevin-owner/state" --key "$HOME/.config/qarevin-owner/keys/owner.private.pem" --token "$HOME/.config/qarevin-owner/authorization.token"
.venv/bin/python scripts/owner_approval.py preview --packet /OWNER_REPORTS/HASH.json --state "$HOME/.config/qarevin-owner/state" --key "$HOME/.config/qarevin-owner/keys/owner.public.pem" --token "$HOME/.config/qarevin-owner/authorization.token"
```

Packet shape is `{"candidate_report": CandidateReport fields}`; use the content-addressed artifact
writer and assemble it from audited source reports. There is no current live-ready packet, because
real broker/forward evidence is absent. Private key/token contents are never printed. Signing keys
are owner-only outside the repo; deployment verification needs only the public key. Ed25519 claims
bind strategy/risk/evidence/broker/account/capital/currency/notional/environment, expire in at most
one hour (default ten minutes), can be revoked, and consume atomically once. Expiry is rechecked
under the consumption lock. Revoke does not close positions.

`DisabledLiveController.prepare` previews without consuming authorization, and `activate` always
refuses: no live actuator is shipped. All approvals in tests are fixtures. No real keys are generated
or tokens issued by automated setup. This completes an offline authorization harness, not live
readiness or permission to deploy real money.
