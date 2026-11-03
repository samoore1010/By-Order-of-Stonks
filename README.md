# By Order of Stonks

A private, paper-first prediction-market research workbench. Built from the EdgeLab brief with a functioning dashboard, durable research jobs, reproducible backtests, a context-aware copilot and opt-in automatic paper strategies.

**Release 0.2.0. Real-money execution is not present.** Synthetic fixtures are labeled throughout and never silently substituted for a failed provider. This is a usable first research release, not a claim that the entire long-term quantitative-desk specification or a profitable strategy is complete.

## Start locally

Python 3.13 is recommended. No Node build or paid account is needed for the sandbox.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_ENV=development uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000`. On Windows PowerShell, activate `.venv\Scripts\Activate.ps1`, set `$env:APP_ENV="development"`, and run the same `uvicorn` command. `.env.example` documents variables; the application does not automatically read `.env`. Export variables in your shell or configure them in Railway.

**Never expose development mode publicly.** Production requires `APP_PASSWORD` of at least 16 characters and `SESSION_SECRET` of at least 32 characters and uses secure, HTTP-only session cookies.

## A complete first workflow

1. Open **Strategy lab**, change the price band and sizing rules, and save a version.
2. Open **Backtesting studio**, select that version and a dataset, set capital/cost assumptions, and click **Run backtest**. Inspect the actual trade ledger, equity, costs and warnings. Compare stored runs or export JSON/CSV.
3. Open **Research lab** to run chronological training/validation/test and execution-cost stress tests. **Agent operations** shows genuine job stages, failures, cancellation, retries and evidence.
4. Open **Opportunity scanner**, explicitly choose synthetic fixtures or Kalshi, and inspect markets. Kalshi requests are real server-side requests; unavailable data produce an error, not fictional quotes.
5. Select a contract to open **Trade builder**. Inspect fresh quoted depth, choose YES/NO, quantity and price, confirm a **paper** ticket, and submit. Inspect cash, positions and IOC fills in **Trading terminal** and **Portfolio & risk**.
6. From the strategy library, explicitly deploy a longshot strategy to automatic **paper-only** scans. Pause its deployment or the entire paper account at any time.

The collapsible copilot is available on every page. Without a model key it is explicitly a local helper. With `OPENAI_API_KEY` it can inspect saved evidence, run authorized backtests/research, retrieve market/weather data, and prepare reviewable strategy/trade drafts. It cannot place orders or change permissions.

## What is implemented

| Capability | This release |
|---|---|
| Dashboard | 12 connected workspaces, responsive mobile navigation, charts, ledger, persistent copilot |
| Persistence | SQLAlchemy, local SQLite or PostgreSQL; transactional account/order writes |
| Strategy engine | Versioned longshot and independent-model-edge rules, fixed-fraction and constrained quarter-Kelly sizing |
| Backtesting | Next-observation entries, cash/settlement accounting, estimated fees, slippage, liquidity caps, event/portfolio limits, JSON/CSV exports |
| Validation | Chronological event-separated partitions, overlapping-horizon purge, training-only parameter search, cost stress, event-bootstrap intervals |
| Research operation | Durable bounded jobs, scheduled reviews of changed datasets, cancellation/retry, restart recovery, audit events |
| Model-backed roles | Optional Director planning and separate qualitative Validator; quantitative gates remain deterministic |
| Data | Kalshi public market/quote readers, selected-contract candle importer with archive routing, validated JSON uploads, current NWS forecasts |
| Paper execution | Separate synthetic and Kalshi-data accounts, fresh-book IOC simulation, partial fills, idempotency, risk caps, halt and settlement reconciliation |
| Autonomous paper | Explicitly approved longshot scans every approximately 60 seconds while the worker is free; page-limited coverage disclosed |
| Integrations | GitHub repository metadata/license/commit intake; portable native strategy JSON and timestamped forecast uploads |
| Combination analysis | Dependence bounds and an explicitly hypothetical independence scenario; **no native combo quotation or execution** |
| Railway | Dockerfile, health check, single-replica configuration, production authentication and deployment guide |

## Important boundaries

This release does **not** install arbitrary repositories, run untrusted Python, reconstruct unavailable historical order books, provide calibrated weather/sports forecasting models, poll the entire exchange exhaustively, or execute real-money orders. GitHub intake is a review registry, not a claim that an imported bot is compatible. Current NWS forecasts are evidence context, not a forecast-probability engine or a point-in-time archive. Paper positions are held to settlement; simulated early exits and maker queues are not implemented.

Real external model calls, authenticated exchange access and Railway deployment require your own provider configuration and were not verified against your accounts. Read [the test report](docs/TEST_REPORT.md) and [architecture/capability boundaries](docs/ARCHITECTURE.md).

## Configuration

| Variable | Purpose |
|---|---|
| `APP_ENV` | `production` by default. `development` only on a trusted local machine |
| `APP_PASSWORD`, `SESSION_SECRET` | Required in production; generate unique random values |
| `PUBLIC_ORIGIN` | Exact deployed HTTPS origin for same-origin checks |
| `DATABASE_URL` | SQLite default or PostgreSQL URL; durable storage required |
| `KALSHI_ENV` | `production` public data by default, or separate `demo`; use separate databases |
| `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PEM` | Optional read-only requests; neither enables trading |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional model-backed copilot; configured on the server only |
| `OPENAI_MAX_CALLS_PER_DAY` | Shared daily request-count cap, default 40; not a dollar spending guarantee |
| `AGENT_LLM_ENABLED` | Explicitly enable model-backed Director and Validator, default false |
| `DIRECTOR_MODEL`, `VALIDATOR_MODEL` | Optional role-specific model overrides |
| `NWS_USER_AGENT` | Application identity with a real contact for NWS requests |
| `GITHUB_READ_TOKEN` | Optional private-repository metadata access; never used to execute code |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m playwright install chromium
python tests/browser_smoke.py
```

The browser test drives the actual frontend against FastAPI's in-process test transport. It verifies connected workflows, not merely static screenshots. It does not validate external credentials, Railway TLS or a production container. Node users may additionally run `node --check frontend/app.js`.

## Documentation

- [Railway deployment and first login](docs/DEPLOYMENT.md)
- [Architecture and operational limits](docs/ARCHITECTURE.md)
- [Data and strategy integration contract](docs/STRATEGY_PLUGINS.md)
- [Kalshi setup and future execution checklist](docs/KALSHI_EXECUTION.md)
- [Executed tests and verification boundaries](docs/TEST_REPORT.md)

The application is original project code; no previously mentioned third-party trading repository has been copied or certified. No open-source redistribution license is assigned here. A public repository's visibility alone does not establish reuse rights for its code or dependencies.
