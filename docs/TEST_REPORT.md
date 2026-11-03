# Build verification

Release: 0.2.0. Verification date: November 3, 2026.

## Executed locally

- `python -m pytest -q`: **60 tests passed** before final publication checks.
- `python tests/browser_smoke.py`: **passed**. Chromium exercised all 12 workspaces, saved a strategy, loaded sandbox markets, submitted a confirmed paper ticket, ran a queued historical backtest, completed a research validation job, used the local copilot and checked a 390px mobile layout. No browser page errors were reported.
- `node --check frontend/app.js`: **passed**.
- `python -m compileall -q backend`: **passed**.

Coverage includes invalid/duplicate/leaking timestamps, next-observation fills, fee rounding, cash conservation, risk caps, quantity limits, paper idempotency, stale quotes, synthetic validation rejection, restart recovery, production authentication, cross-origin protection, blocked live orders, combo dependence bounds, RSA/Ed25519 signatures, archived candle normalization, model-call budgeting, actual copilot tool dispatch using a mocked model, and qualitative-review permission boundaries.

## Not claimed as verified

The browser test connects to actual FastAPI logic via an in-process bridge; it is not a Railway deployment test. OpenAI responses in provider-specific tests are mocked. Real model access/billing and authenticated Kalshi calls require owner credentials. PostgreSQL deployment and Docker build have not been executed in this build environment.

An unauthenticated external Kalshi smoke request was attempted but network access from this environment failed with `Kalshi could not be reached`. No live quote success is claimed and no synthetic response was substituted. Schema-level adapter tests passed against explicit fixtures.

The test suite verifies software behavior, not investment profitability, a complete historical universe, calibrated independent forecasts or real-world execution quality.
