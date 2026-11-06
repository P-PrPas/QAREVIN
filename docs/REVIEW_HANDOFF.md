# Owner review handoff

QAREVIN's offline engineering harness is implemented across seven open, unmerged PRs.
Engineering completion does not establish strategy performance or production readiness.

| Order | Scope | PR | Base |
|---|---|---|---|
| 1 | F0 contracts, configuration, resources and CI | https://github.com/P-PrPas/QAREVIN/pull/1 | main |
| 2 | F1 immutable data, causal strategies and backtest | https://github.com/P-PrPas/QAREVIN/pull/2 | phase/f0-foundation |
| 3 | F2 independent evaluation, lineage, replay and holdout | https://github.com/P-PrPas/QAREVIN/pull/3 | phase/f1-research-engine |
| 4 | F3 Hermes profile, API/MCP and bounded workers | https://github.com/P-PrPas/QAREVIN/pull/4 | phase/f2-evidence-evaluation |
| 5 | F4 demo execution safety and bridge client | https://github.com/P-PrPas/QAREVIN/pull/5 | phase/f3-hermes-research |
| 6 | F5 owner signing and disabled-live approval harness | https://github.com/P-PrPas/QAREVIN/pull/6 | phase/f4-demo-safety |
| 7 | F6 research lifecycle, observations, alerts and recovery | https://github.com/P-PrPas/QAREVIN/pull/7 | phase/f5-owner-approval |

Review and merge bottom-up. Merge commits preserve stack ancestry. After merging each parent,
retarget its child to main and confirm the remaining diff/checks. Squashing a parent requires
restacking descendants before continuing. No PR has been merged automatically.

All later review rounds reuse one Lab / Claude Opus 5.5 medium thread:
t3-thread://v1/mcp:5bf216ef-394d-4905-8372-05c8140b8300
Findings/responses and the two-round limit per PR are recorded under `docs/reviews/`.

## Verification and its limits

- Local full pytest, Ruff and Compose validation cover the assembled stack; final counts and
  CI status are recorded in the delivery message. Tests use synthetic fixtures.
- Twenty deterministic bounded worker cycles exercise queue, artifacts, quota and failures;
  they do not exercise a language model or establish prompt-injection resistance.
- Pinned Hermes image was tested as UID 1000 with dropped capabilities, read-only root and no
  network: CLI startup and real SDK stdio MCP discovery of 15 tools passed without model calls.
- F3 container image API/auth/job/isolated-worker integration passed. This is evidence for that
  earlier exact image, not a claim that every later commit was rebuilt or deployed.
- FakeBroker fault tests and demo smoke exercise uncertainty/reconciliation/risk controls.
  No actual broker session, order, forward month or owner authorization was created.
- Research checkpoint restore/replay uses a fresh directory, external archive digest and latest
  known audit prefix. Owner holdout, execution and approval stores are not cloned.

## Required external evidence and deployment work

1. Supply real owner-controlled CSVs, source timezone/DST policy, broker symbol/contract details,
   trading calendar, historical spreads/costs, provenance and a genuinely untouched holdout.
   Verify the configuration before any demo use. Research release attestations are owner actions.
2. Configure a separate Hermes profile with model credentials and run semantic/injection/spend
   acceptance tests. Parameter-only experiments are supported; arbitrary generated code execution
   and its sandbox acceptance remain disabled/pending. No cron or chat sender was installed.
3. Implement/deploy the actual MT5/broker bridge server and validate the selected broker against
   the bridge client contract, including stop/fill/margin/account-identity behavior.
4. Run at least three real forward calendar months and collect sufficient independently validated
   fill/deal evidence. Sampled account snapshots and fake-broker tests cannot satisfy this gate.
5. Review real evidence, capital limits and owner policy before issuing any narrowly scoped
   approval. Live activation is deliberately disabled and no live actuator is implemented.
6. Native MQL5 EA export is not implemented; it needs its own specification and parity validation.

See `DEVELOPMENT_PLAN.md`, `IMPLEMENTATION_STATUS.md`, README and `docs/runbooks/` (where present)
for configuration, operating procedures and the distinction between harnesses and evidence gates.
No defensible percentage of trading readiness can be derived from code/tests alone.
