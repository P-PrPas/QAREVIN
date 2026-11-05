---
name: quant-research
description: Run bounded XAUUSD experiments, interpret completed evidence, or prepare promotion requests with the Qarevin tools.
---

1. Read `market_list_datasets`, recent `memory_get` and relevant `registry_get_lineage`.
   Continue when coverage/QA and a frozen baseline are identified. If missing, report what blocks research.
2. State one falsifiable hypothesis, expected effect, maximum trials and stopping criterion through
   `research_propose`. Continue only after a hypothesis ID is returned.
3. Register parameter-only strategy through `research_submit_candidate`, with parent ID and one
   substantive change. Preserve original baseline. Generated source is unavailable in this version.
4. Queue backtest or walk-forward using the returned candidate/dataset IDs and a stable idempotency
   key. State queued/running status. Wait for completion through subsequent status checks rather
   than issuing duplicate jobs. Stop on quota, stale version, data error or insufficient evidence.
5. Read the succeeded result; compare matched baseline/challenger jobs with `research_compare`.
   Quote experiment ID, evidence kind, net costs, drawdown, trade count, missing gates and limitations.
   Null metrics mean insufficient/undefined evidence. Never convert them into a high score.
6. Record observation, alternative explanations and a next falsifiable test with `memory_record`.
   Completion means the immutable result and memory IDs are returned. Keep failures in the record.
7. If P requests promotion, use the request tool and state its actual gate status. Holdout is an
   owner-only milestone; demo needs broker validation/owner activation; live needs forward evidence,
   capital policy and authenticated authorization. A request is never a deployment.

Demo/live score gaps require checking feed, costs, fills, risk, regime and sample noise before
attributing overfit. Historical tuning is feedback-guided search, not RL weight training.
