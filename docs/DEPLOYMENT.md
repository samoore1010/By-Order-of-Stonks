# Railway deployment

This publishes a private application from the feature branch. It does not enable real-money execution. The repository can be private; GitHub visibility and application authentication are independent.

## Service configuration

1. In Railway, create a service from `samoore1010/By-Order-of-Stonks` and select branch `feature/stonks-research-workbench`. Keep the repository root as the build root.
2. The checked-in `Dockerfile` and `railway.json` supply build/start configuration. Do not add a Node build command. The server listens on Railway's `PORT` and `/healthz` is the health-check endpoint.
3. Add durable storage **before using the application**. Simplest: mount a Railway volume at `/app/data` and set `DATABASE_URL=sqlite:////app/data/stonks.db`. Alternatively attach PostgreSQL and set `DATABASE_URL` to its connection URL. Do not use ephemeral container storage for research or paper accounts.
4. Set `APP_ENV=production`. Generate unique random values for `APP_PASSWORD` (16+ characters) and `SESSION_SECRET` (32+ characters). For example, run `python -c "import secrets; print(secrets.token_urlsafe(48))"` twice locally. Never commit the generated values or paste them into the copilot.
5. Generate a public HTTPS domain. Set `PUBLIC_ORIGIN` to that exact origin, without a path, for example `https://your-service.up.railway.app`.
6. Deploy and open the domain. Sign in with `APP_PASSWORD`. Confirm the sandbox banner, functioning workspaces and worker heartbeat in Settings.

Use **one replica and one Uvicorn worker**. The scheduler and paper-execution locks are process-local. Multiple replicas or overlapping deployments can duplicate background work. PostgreSQL support does not remove that limitation. Pause deployments and scheduled research before rolling updates; use Railway's zero-overlap setting where supported and wait for the previous process to stop.

## Optional services

Set `OPENAI_API_KEY` and a Responses-API-compatible `OPENAI_MODEL` for the conversational copilot. Model access and billing are account-specific. The default model identifier is configurable and has not been authenticated against your account. `AGENT_LLM_ENABLED=true` additionally enables model-backed research planning and critique. They share the request budget and cannot authorize real trades.

Set `NWS_USER_AGENT` to the application name plus your contact. Configure Kalshi read credentials only if required for your chosen endpoints. See [Kalshi setup](KALSHI_EXECUTION.md). No credential is required for the synthetic sandbox.

## Smoke test after deployment

Open each workspace. Save a strategy, run a backtest, launch a validation job and confirm completion. Place a small synthetic paper order and reconcile a sandbox settlement. Confirm the paper halt button blocks new orders. Separately test a public Kalshi fetch; if it fails, inspect the explicit error and server network access. Do not interpret synthetic fixtures as a successful provider connection.

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
