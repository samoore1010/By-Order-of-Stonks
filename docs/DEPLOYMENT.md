# Railway deployment

This publishes a private application from the feature branch. It does not enable real-money execution. The repository can be private; GitHub visibility and application authentication are independent.

## Service configuration

1. **Preview only:** create a separate staging service from the repository branch `rebuild/market-intelligence-desk`, leaving the existing production deployment on `main`. Keep the repository root as the build root. Do not attach the production SQLite volume to two active services.
2. The checked-in `Dockerfile` and `railway.json` supply build/start configuration. Do not add a Node build command. The server listens on Railway's `PORT` and `/healthz` is the health-check endpoint.
3. Add durable storage **before using the application**. Simplest: mount a Railway volume at `/app/data` and set `DATABASE_URL=sqlite:////app/data/stonks.db`. Alternatively attach PostgreSQL and set `DATABASE_URL` to its connection URL. Do not use ephemeral container storage for research or paper accounts.
4. Set `APP_ENV=production`. Generate unique random values for `APP_PASSWORD` (16+ characters) and `SESSION_SECRET` (32+ characters). For example, run `python -c "import secrets; print(secrets.token_urlsafe(48))"` twice locally. Never commit the generated values or paste them into the copilot.
5. Generate a public HTTPS domain. Set `PUBLIC_ORIGIN` to that exact origin, without a path, for example `https://your-service.up.railway.app`.
6. Deploy and open the domain. Sign in with `APP_PASSWORD`. Confirm the Explore, Research and Trade workspaces, accessible source coverage and research worker status. The old prototype is at /legacy.

Use **one replica and one Uvicorn worker**. The scheduler and paper-execution locks are process-local. Multiple replicas or overlapping deployments can duplicate background work. PostgreSQL support does not remove that limitation. Pause deployments and scheduled research before rolling updates; use Railway's zero-overlap setting where supported and wait for the previous process to stop.

## Optional services

Set `OPENAI_API_KEY` and a Responses-API-compatible `OPENAI_MODEL` for the conversational copilot. Model access and billing are account-specific. The default model identifier is configurable and has not been authenticated against your account. `DESK_MODEL_PLANNING=true` enables model-assisted research planning; `DESK_WEB_RESEARCH=true` enables optional public web context. `DESK_AUTONOMOUS_ENABLED=true` permits a bounded daily automatic market study. They share the request budget and cannot authorize real trades.

Set `NWS_USER_AGENT` to the application name plus your contact. Configure Kalshi read credentials only if required for your chosen endpoints. See [Kalshi setup](KALSHI_EXECUTION.md). Public Kalshi market data do not require private trading credentials; the new interface does not use synthetic market data.

## Smoke test after deployment

Open Explore, Research and Trade. Confirm actual Kalshi series and indexed contracts appear. Start a free-form investigation, wait for automatic history collection, and inspect the report's historical coverage and explicit limitations. Review a real open contract's rules and submit a small **paper** ticket only. Confirm pause blocks new paper orders. Verify upstream Kalshi and model-provider connections independently; local mock tests do not validate network access.

Before leaving automatic paper scanning on, review the chosen source, strategy, series filter and documented page limit. Scheduled historical research does not automatically discover or ingest new historical datasets; it rechecks the selected dataset only when its contents change.

## Operations

Back up the database using the storage provider's supported backup mechanism. Stop the application before copying a SQLite database file. Database records include private research, chat messages and paper positions. Never commit `data/`, populated environment files, private keys or logs.

The health endpoint reports whether the worker task is alive, not whether every upstream provider is reachable. API failures appear as job errors. Long imports share a worker with scans; this is not an HFT or real-time SLA design. Restarted running jobs become `interrupted`, not silently completed. Retry them from Agent Operations.

## Official deployment references

- Dockerfiles: https://docs.railway.com/guides/dockerfiles
- Health checks and `PORT`: https://docs.railway.com/deployments/healthchecks
- Volumes: https://docs.railway.com/volumes/reference
- Variables: https://docs.railway.com/variables/reference

Reviewed November 3, 2026. This branch has not been deployed to your Railway account.
