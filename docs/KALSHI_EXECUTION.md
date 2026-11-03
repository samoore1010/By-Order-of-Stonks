# Kalshi setup and future live execution

## What works now

The Kalshi adapter performs **GET requests only**. It supports explicit public market browsing, fresh order-book reads, selected-contract historical candle imports and optional signed reads. Paper trades remain database entries in this application; they are not sent even to Kalshi's demo order endpoint.

Production market data and actual-money execution are different concepts. `KALSHI_ENV=production` reads production exchange data, but all orders in this release remain simulated. No environment flag can unlock real-money execution.

The adapter uses the documented endpoints:

| Environment | REST base |
|---|---|
| Production | `https://external-api.kalshi.com/trade-api/v2` |
| Demo | `https://external-api.demo.kalshi.co/trade-api/v2` |

Source: https://docs.kalshi.com/getting_started/api_environments

## Optional authenticated reads

Create credentials in the appropriate Kalshi account environment. Demo and production credentials are distinct. Use the account's available least-privilege/read-only permissions. Keep the private key in server-side secret storage, never in GitHub, browser code, an uploaded dataset, or the copilot conversation.

Set `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM`; actual multiline PEM and escaped `\n` values are supported. Ed25519 and RSA-PSS/SHA-256 keys are supported. Requests sign the timestamp, method and API path excluding query parameters. Changing environment requires a separate database so paper accounts cannot mix venues.

Source: https://docs.kalshi.com/getting_started/api_keys

## Historical imports

In Data & Intelligence choose a series, exact settled contract tickers and a date range. Imports are bounded to 20 tickers and 365 days per job, with hourly/daily candle intervals. The adapter reads `/historical/cutoff`, selects the current or historical candle route and stores partial errors and rules provenance. Only final ordinary $1 binary settlements are supported. Missing settlement timestamps or unsupported payouts are rejected rather than guessed.

This is not an exhaustive historical exchange download. The selected settled universe can be biased. Candle-end bid/ask data do not establish queue position or historical available depth. Market rules retrieved today are not proven to be the version in force historically.

Source: https://docs.kalshi.com/getting_started/historical_data

## Production execution remains a separate release

The requested long-term path is preserved through versioned strategies and a central order service, but completing it safely requires additional implementation and acceptance testing:

1. Reverify account eligibility, current API specifications, fees, permissions, order-side mapping and allowed products. Do not copy an older create-order payload without checking the current specification.
2. Add a dedicated authenticated execution adapter, separate credentials and an explicit production authorization policy. Keep research and third-party models outside the credential boundary.
3. Implement a durable order state machine, client-ID idempotency, unknown/timeout resolution, partial fills, cancellations and exchange balance/position reconciliation. Never blindly retry a timed-out order.
4. Combine fresh quotes with pre-trade cash, concentration, price/slippage, order and strategy limits. Enforce risk checks independently of model output.
5. Test in Kalshi's demo environment, including network failure, stale streams, restart recovery, partial fills, rate limits and emergency cancellation. Demo fills do not prove production liquidity.
6. Make live activation an explicit owner-approved release. Start with tightly bounded manually approved trades and compare actual costs/fills against paper assumptions before enabling any systematic live mode.
7. Implement an emergency stop that blocks new orders and attempts cancellation. It cannot undo fills or guarantee cancellation during network failure.

Native combination products require their actual supported quotation and execution flow and joint-event modeling. The current combination calculator is intentionally **not** an exchange quote and must not be converted into separate orders while claiming atomic combo execution.

Official implementation reference: https://docs.kalshi.com/ . Recheck at deployment. No funded account was connected and no real orders were placed during this build.
