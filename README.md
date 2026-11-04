# By Order of Stonks

## Capability-aware research upgrade (new branch)

The research desk now distinguishes market investigations, historical comparisons,
event-specific questions and multi-leg trade construction. It preserves user
constraints, checks original source records, verifies supported sporting events,
and **refuses to present an unrelated generic backtest as an answer**.

See [capability-based research architecture](docs/CAPABILITY_RESEARCH.md) for
request planning, official exchange evidence, bounded sports player game logs,
provisional multi-leg structures and the evidence required before any joint
probability or execution claim can be certified.

**The current stage is experimental.** Real-money execution and native
combination RFQs remain disabled. Broad market analysis is supported, but
unavailable correlation models, incomplete historical coverage or unsupported
providers will be identified as unfulfilled requirements rather than guessed.



## Research-first market intelligence desk

This branch rebuilds the project around one workflow: **ask a question, find
real Kalshi markets, collect available history, run reproducible research,
review the evidence, and optionally place a paper trade.**

There are THREE primary user workspaces: **Explore**, **Research**, and
**Trade**. The previous twelve-tab interface is retained at the /legacy
route for comparison only. Generated market fixtures are not shown in the new
research interface.

### What works on this branch

- Indexed, durable SQL storage of real Kalshi series, contracts and historical
  bid/ask candlesticks, including retrieval from the separate archive.
- Background bounded synchronization of current markets, plus research-driven
  discovery of relevant settled contracts without requiring ticker entry.
- Market-agnostic user research questions, model-assisted task planning when
  configured, and deterministic fallback search when no model key is available.
- Chronological reference price selection; empirical outcome calibration by
  probability band; comparisons by series, category and inferred market type.
- Common baseline simulations: buy YES, buy NO, longshots, favorites and
  buying NO against low-priced YES contracts; adjustable price, liquidity,
  entry-horizon and sampling constraints.
- Event-level uncertainty and explicit warnings for limited samples,
  survivorship, missing contract data, correlation and unavailable historical
  order-book depth.
- Optional public research using an OpenAI-compatible Responses API model
  with web-search capability, with source links where provided. Web context
  is not used as historical point-in-time data.
- Durable job progress and failures, saved reports, and a bounded daily
  unattended research scan across real, liquid series.
- Existing, separately enforced cash-account paper trading with fresh
  order-book data, exposure limits and manual approval.

### What does not work yet

This is not a universal prediction or autonomous trading engine. It cannot
reconstruct historical available resting depth, execute real-money trades,
price native combinations, ingest every historical contract at once, or
build reliable independent forecasting models for every event category.
Market subtype classification is inferred from contract text; series coverage
is bounded and must be reviewed. No strategy has been demonstrated to
produce an investable edge.

The examples of elections and professional sports are acceptance scenarios,
not hardcoded categories defining the research system.

### Development

Python 3.13 is recommended. With requirements installed, start locally using:

    APP_ENV=development uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000 for the new interface. The prior version is at
http://127.0.0.1:8000/legacy.

Development-mode startup does not automatically call external providers.
An explicit research job retrieves available data; tests use mocked market
responses, not invented investment evidence.

Check:

    python -m pytest -q
    node --check frontend/desk.js
    python -m playwright install chromium
    python tests/browser_desk.py

### Production environment

This branch has NOT been deployed to Railway. Deployment may reuse the
existing single-replica service and durable database volume after
acceptance testing.

Required for public hosting: APP_ENV=production, a unique APP_PASSWORD
of at least 16 characters, SESSION_SECRET of at least 32 characters, and
the correct PUBLIC_ORIGIN.

Optional service variables:

| Variable | Role |
| --- | --- |
| DATABASE_URL | Existing persistent SQLite volume or PostgreSQL |
| KALSHI_ENV | Production or demo, with separate stored environments |
| KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PEM | Optional authenticated read API |
| OPENAI_API_KEY | Research planning, explanation and optional web context |
| OPENAI_MODEL | Responses-compatible model available on the account |
| OPENAI_MAX_CALLS_PER_DAY | Shared model request budget; not a dollar budget |
| DESK_MODEL_PLANNING | Enable model-based research planning |
| DESK_WEB_RESEARCH | Allow optional public web context |
| DESK_AUTONOMOUS_ENABLED | Allow a bounded daily research job |

Do not commit private keys, API secrets or application passwords. Production
trading remains disabled even if the exchange credential has write permissions.

See docs/RESEARCH_DESK.md for architecture, how to reproduce a study,
data-quality methodology, and unresolved limitations. See
docs/DEPLOYMENT.md for the existing Railway configuration.
