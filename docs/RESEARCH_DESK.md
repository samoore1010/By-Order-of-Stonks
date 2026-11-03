# Research Desk: architecture, evidence policy and deployment

## Product concept

One free-form research question triggers a bounded, observable series of tasks:

1. Research-plan interpretation, with a deterministic fallback if the configured
   model is unavailable.
2. Search the provider-grounded series directory and current indexed markets.
3. Retrieve matching current and historically settled contracts, including
   the historical archive after the cutoff.
4. Collect historical bid/ask daily candles for qualifying $1 binary contracts.
5. Select historical decision-time reference quotes, calculate empirical
   calibration and compare baseline trading strategies on the same records.
6. Expose sample size, event clustering, execution assumptions, missing data,
   the selected market/series universe and actual source URLs.
7. If available, request separately labeled public web context. Current
   web-search material is NEVER substituted into a historical backtest.
8. Save a report and optionally discuss its findings conversationally.
9. Independently inspect a real current Kalshi contract to simulate a paper
   order. The research process cannot submit a real-money order.

Explore, Research and Trade are views on the same data, rather than a
wizard that demands technical market ticker entry from the user.

## Backend components

- backend/market_catalog.py: SQL series/market/candle tables, pagination,
  event/series metadata, current indexing and archive routing.
- backend/quant_research.py: price-band empirical calibration, event-level
  uncertainty, market-type/category/series comparisons and event-driven
  trading-rule simulations with explicit fee/volume assumptions.
- backend/desk.py: research planner, persistent job state, optional external
  context, scheduled bounded market investigations and authenticated API.
- backend/app.py: private web auth, integration and service lifecycle.
- frontend/desk.html, desk.css, desk.js: three-workspace application.
- backend/service.py, paper.py: original cash-only paper-order engine.
- The old interface remains at /legacy while its old APIs remain supported.

## API routes

All paths below are owner-authenticated in production:

- GET /api/desk/overview: real catalogue coverage, jobs, reports, worker and
  paper account (no private credentials returned).
- GET /api/desk/markets: indexed market search by query, category and status.
  Pagination is explicit; absence is not proof that a Kalshi contract does not exist.
- GET /api/desk/series: series matched by title, category, tags and ticker.
- GET /api/desk/market/{ticker}: exact indexed contract, retrieved history and rules.
- POST /api/desk/research: queue a new empirical investigation.
- GET /api/desk/jobs/{id}: real progress, timestamps and failures.
- GET /api/desk/reports/{id}: saved result and collection provenance.
- POST /api/desk/chat: create a research job or discuss an existing report.
- POST /api/desk/paper: explicit confirmation routed to the existing cash-only
  risk-limited simulator. It cannot invoke production exchange writes.

No exchange order-creation endpoint exists in this release.

## Market indexing and coverage

The series listing provides top-level titles, categories, tags, and template
identifiers. The live market store and historical market archive are
paginated independently. The app retains result status, settlement timestamp
and text/metadata for each contract.

Automatic on-start indexing in production is bounded (the first two pages of
open markets and the provider's current series directory). A user research
question searches relevant series and fetches their open and settled markets
directly, independently of the generic index pages.

The number of series and settled contracts collected per research job is
limited. Truncation and endpoint errors are saved. Because discovery is scoped,
results are exploratory rather than guaranteed comprehensive. No claim of
market absence, edge, or exhaustive market coverage is justified solely by
this index.

The configured Kalshi environment must match its own persistent database;
do not mix demo records and production records.

## Historical simulation methodology

Only settled ordinary binary contracts with actual YES/NO results and a
settlement timestamp are eligible. Other payout formats and incomplete
settlements are excluded explicitly.

For a selected decision horizon, the simulator selects the latest
historical candle at or before the decision timestamp (usually two days
before actual settlement), rejecting quotes more than 72 hours stale.

Calibration compares actual settlement frequencies against quoted YES
midpoints across probability bands. This is descriptive, not a trading
model, and midpoints are not necessarily executable.

Trading baselines use hypothetical entry prices:

- Buy YES: observed YES ask plus modeled adverse slippage.
- Buy NO: one dollar less the observed YES bid plus modeled slippage.
- Longshot and favorite baselines constrain the candidate price ranges.

Fees are modeled rather than reconstructed from historical exchange fee
schedule snapshots. Liquidity is approximated by a conservative fraction
of observed candle trading volume, NOT order-book resting depth. One
position per contract, per-event caps, aggregate exposure caps and cash
locked through settlement are included.

There is no claim that these entry prices or quantities could have
been obtained. Notional drawdown is shown at committed cost; it does not
replace a proper historic mark-to-market drawdown.

The model cannot prove a reliable edge from small samples. Report
limitations include event-level clustering, correlated underlying
events, selection bias, survivorship and data availability gaps.

## External research and probability models

A configured Responses API model may plan tasks and request the provider's
public web-search tool for fresh context. Source citations are retained
when supplied. This is intentionally separate from quantitative evidence.

To evaluate a truly independent fair-value estimate, the platform still
requires point-in-time domain-specific forecast datasets and calibration.
For example, fresh web search results cannot be used as information that
was supposedly available on historical dates. The system must mark that
type of independent probability model as unavailable until a real
provider-specific integration is built.

## Autonomous jobs

In production, a bounded series refresh and current market-index job runs
about every 30 minutes while the service is awake. If enabled, the desk
selects up to one series-level calibration investigation per UTC day from
the most liquid indexed series, with diversity across provider categories.

Autonomous jobs use actual market records and explicit performance
limitations. They do not continuously call multiple language models,
modify their own strategy code, or initiate production orders.

Research jobs execute on a single process-local worker. As presently built,
run precisely one replica and one Uvicorn worker. Production rolling
updates may still need zero overlap to avoid duplicate background work.

## Deployment and security

This branch is for testing and review. Do not merge or deploy to the
existing production project without explicit approval.

The existing Railway single-service configuration and durable volume can
be reused. Run the same Dockerfile and single-worker start command.
A separate Redis service or Postgres instance is not required for a
single-replica demonstration, though production-scale indexing should
eventually migrate to durable analytics storage.

Production start requires an application password and signed session
secret. API credentials are server-side only; the new interface is not
authorized to submit real-money orders.

Model API costs are shared with the older application under the existing
OPENAI_MAX_CALLS_PER_DAY request counter. This is not a dollar spending
cap: configure provider-level spending limits separately.

Use tests/test_desk_core.py and tests/browser_desk.py to reproduce the
behavior with mocked provider responses. Real exchange connectivity
must be checked explicitly in the deployed environment.

## Important next engineering milestones

1. Comprehensive, resumable historical backfill with job quotas and
   contract universe audit, not just a bounded research sample.
2. Point-in-time external forecasting adapters, data licensing and
   quantitative uncertainty calibration.
3. Stronger systematic market-type classification using source metadata,
   reviewable human corrections and market-rule relationships.
4. Higher-fidelity execution simulation using prospectively captured
   order-book history, fees by historical schedule and maker/taker fills.
5. A verified strategy DSL / plug-in sandbox that can express novel
   research hypotheses, not just the supported baseline family.
6. Automated alerts and paper-strategy activation after independent
   validation; no production trading until explicitly authorized.

This branch is not presented as completion of those later milestones.
