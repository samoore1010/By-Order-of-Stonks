# Architecture and release boundaries

## Deployment shape

The first deployable release is a modular Python/FastAPI service serving a dependency-free browser frontend. It deliberately avoids a separate Node build, Redis service and several independently deployed agents for this initial single-user version. The original Next.js/multi-service brief remains a future scaling option, not the implemented stack.

```
Browser workbench + context-aware copilot
                 |
      Authenticated FastAPI service
       /         |             \
Research worker  Paper ledger   Provider adapters (read-only)
       |         |             | Kalshi / NWS / GitHub / optional OpenAI
       +----- SQLAlchemy record store -----+
                SQLite or PostgreSQL
```

`backend/models.py` validates strategy and dataset contracts. `engine.py` is the deterministic historical simulator. `service.py` owns persistence, queued jobs, research validation, scheduled research and automatic paper scans. `paper.py` is cash-only IOC execution simulation. `providers.py` contains allowlisted, read-only adapters. `copilot.py` is the bounded model tool loop. `agents.py` supplies optional Director and separate qualitative Validator calls. `app.py` supplies authentication, API routes and the static frontend.

All 12 workspaces use actual backend operations: Command Center, Opportunity Scanner, Research Lab, Strategy Lab, Backtesting Studio, Trade Builder, Trading Terminal, Portfolio & Risk, Agent Operations, Data & Intelligence, Integrations and Settings.

## Research correctness

A strategy only reads selected observable features, never outcome labels. Entry signals come from a prior completed observation and execute on the next observation, at its ask plus configured slippage. This reduces same-bar look-ahead but does not prove historical execution. Missing depth is approximated with a volume participation cap and is explicitly disclosed.

The engine holds to binary $1 settlement, accounts for simultaneous cash commitments and marks open positions at bid before hypothetical exit fees. Risk budgets use starting capital. Category rules, risk fractions and cost assumptions are inspectable. Quarter-Kelly requires timestamped independent probabilities. Contract-level calibration and win rates alone are not evidence of profit.

Research jobs split chronologically by event IDs, purge overlapping settlement horizons, choose among bounded parameter variants using training data only, then report validation, test and stressed test. Event-block bootstrap is descriptive and does not correct hidden dependence or repeated hypothesis searching. User-uploaded provenance is not independently verified. A synthetic dataset cannot pass the non-synthetic validation gate. No validation result enables live execution.

## Autonomous operation

No six perpetual chatbots run in the background. The worker performs actual scheduled/deterministic work. Optional LLM roles activate only for substantive planning and critique. Every stage is labeled deterministic, model request, model result or fallback. The Director does not receive held-out outcomes. A qualitative reviewer cannot overwrite numerical checks or approve trades.

Scheduled research re-evaluates a chosen dataset only after its content hash changes and within a job-count limit. It is **not** unrestricted autonomous market discovery. Paper deployments separately poll one page of current markets, apply an approved longshot strategy, fetch fresh quotes and simulate orders. Coverage is recorded. The current live adapter does not supply independent forecast probabilities, so model-edge automated paper deployment is blocked.

## Security and execution

Production requires authentication. Cookies are signed, HTTP-only, Secure and SameSite Strict. Mutating requests require an application header; origin checks and restrictive content security policy reduce cross-site request risks. Provider keys never reach the browser or model prompts. There is no shell, arbitrary URL fetch or imported-code execution tool.

Paper request IDs are idempotent; conflicting reuse fails. Account and order writes occur in one transaction under a process-local execution lock. Repeated orders cannot refill an unchanged displayed book indefinitely. Account-wide contract/event/total caps and halt state are enforced in code. The copilot has no order-submission or permission-edit tool. Real-money endpoint requests always return 403.

The app is not hardened for a hostile multi-tenant service. Use one trusted owner, strong credentials, TLS, backups and one process. Multi-replica deployment needs distributed locking, durable queue claims and stronger identity/access design before it is safe.

## Explicit future scope

- Full point-in-time market-universe discovery and historical order-book storage.
- General strategy plugin execution in isolated containers after license/security review.
- Calibrated weather/sports/economic forecasting and licensed historical information.
- Multi-venue comparisons and native exchange-supported combination quotes/orders.
- Limit-order queue simulation, early exits, advanced position/risk optimization.
- Live-order state machine, exchange reconciliation, externally enforced risk controls and a separately authorized production release.

These features are not simulated by decorative UI or implied to exist merely because the corresponding concept appears in the product brief.
