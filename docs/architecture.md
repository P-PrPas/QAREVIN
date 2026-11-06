# Trust boundaries

Hermes → scoped MCP/control API → durable job controller → parameter-only research worker.
Trusted engine calculates fills and equity; trusted evaluator calculates gates from those fills.
Generated Python is not imported into any trusted process. Arbitrary code execution stays disabled
until an isolated runner is proven. Research has no broker implementation or order credentials.

Deployment uses pinned strategy signals → risk reservation → adapter, never an LLM order call.
Demo/live states, credentials, identities and processes are separate. No live service is shipped enabled.
Unknown broker results halt entries until reconciliation; client IDs alone do not provide exactly-once.
Holdout data must be in an owner-only store outside agent-visible dataset roots.

The repository is qarevin/ itself, not the enclosing Hermes project. Existing agents are not modified.
Config examples contain synthetic contract/cost/session values, unsuitable for deployment.
