# Demo bridge contract (not a validated MT5 integration)

HTTPDemoAdapter defines the private terminal/API boundary. A broker-specific bridge server is
**not supplied or selected yet**. Validate one on Windows MT5/private TLS network or the broker's
supported API before any demo activation. Python MT5 is not assumed to run natively on this host.

Every endpoint authenticates a dedicated runner-only bearer secret and binds these headers against
the terminal's actual account on every operation: X-Qarevin-Environment=demo, X-Qarevin-Account,
X-Qarevin-Server. Reject live or mismatching terminal identities before any order call. Broker secrets
and this bridge token never enter the research/Hermes services. HTTPS is mandatory off loopback;
redirects, environment proxies and automatic submission retries are disabled.

Responses match strict models in broker.py/domain.py (unknown fields rejected):

- GET /v1/health → Health {connected:bool}
- GET /v1/account → Account, including actual environment, equity/margin and verified cumulative cash flows
- GET /v1/instruments/{broker_symbol} → InstrumentSpec; point/tick/lot/stop/margin units must be normalized
- GET /v1/quotes/{broker_symbol} → aware UTC Quote; never substitute a cached bar for a fresh executable quote
- GET /v1/positions → Positions {positions:[Position]}; include manual/unowned positions for reconciliation
- GET /v1/orders → Orders {orders:[OrderResult]}; include all pending orders, even unowned
- GET /v1/orders/{client_id} → Find {found:bool,order:OrderResult|null}; missing is not proof an uncertain order was never accepted
- POST /v1/orders with Order → OrderResult; persist intent/client correlation before calling terminal
- POST /v1/orders/{client_id}/cancel → OrderResult; confirm remainder cancellation after partial fill
- POST /v1/positions/{position_id}/close → CloseResult {closed:bool}; true only after verified fill/position disappearance

The server must persist full client IDs and correlate terminal order/deal/position history. MT5
comments/magic IDs alone are not an exactly-once guarantee; after transport timeout query broker
state and leave unknown states blocked. It must enforce supported fill modes, account netting vs
hedging, minimum/freeze stop levels, fees and margin/profit calculations on the selected broker.
Do not reconstruct a missing stop from an assumption: read actual server protection.

Response bodies are limited to 1 MiB; positions/open orders to 100. Symbol suffix mapping is explicit,
including validation of returned symbols. Cash-flow verification must distinguish trading PnL from
deposits/withdrawals so restart/daily risk baselines cannot reset drawdown. If history is incomplete,
return unverified/fail closed. Static margin_per_lot backtest estimates require comparison against
actual broker margin before adapter acceptance; this is a deployment gate, not evidence from mocks.

Margin is dynamic: POST /v1/margin with the normalized Order returns
`{required_margin: positive finite account-currency amount}` from the terminal's margin calculator.
The runner compares static contract terms separately, excluding `margin_per_lot` and local `verified`.
It validates actual per-order margin against free margin and policy before reserving/sending.
OrderResult replies, including open orders, lookup and cancellation, must include actual broker
symbol; unmapped symbols freeze entries rather than silently adopting another instrument.
