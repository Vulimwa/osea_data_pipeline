# Developer and service setup

This project has a backend/data pipeline in `osea_data_pipe` and a separate React map in `frontend`. The backend connects to Earth Engine and PostgreSQL/PostGIS; the browser communicates with the backend API only.

## Prerequisites

- Node.js and npm.
- Python matching the project environment and packages in `requirements.txt`.
- A PostgreSQL database with PostGIS enabled.
- Earth Engine access for each configured source asset and an Earth Engine-enabled Cloud project.

## Install and configure the backend

From `osea_data_pipe`:

```powershell
npm ci
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set real values in the local `.env` or deployment secret manager. Important settings:

| Variable | Purpose |
| --- | --- |
| `DB_URL` | PostgreSQL/PostGIS connection. `DATABASE_URL` and `SUPABASE_DB_URL` are supported aliases. |
| `GEE_PROJECT_ID` | Cloud project used by Earth Engine initialization. |
| `GEE_SERVICE_ACCOUNT_EMAIL`, `GEE_SERVICE_ACCOUNT_KEY_PATH` | Optional service-account credentials. Store the key outside the repository. |
| `GEE_ASSET_*` | Full IDs for the configured Earth Engine feature-table inventory. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Server-side bearer-token verification in production. |
| `CORS_ORIGIN` | Exact allowed browser origin(s) for production. |
| `OSEAS_PUBLIC_READ_API` | Optional explicit public access for read-only GET routes. |
| `NASA_FIRMS_MAP_KEY` | Optional server-side key for the FIRMS adapter. |

Never commit credentials or copy them into frontend variables. If a secret has been exposed, rotate it before running any database write.

## Create/check the database

Apply [`../database/schema.sql`](../database/schema.sql) to the intended Supabase/PostgreSQL database. It creates OSEAS objects additively; it is not a data reset. Then run:

```powershell
npm run db:setup
```

This is a read-only connectivity/schema check. It does not apply the SQL file or migrate legacy tables.

## Check Earth Engine assets

```powershell
npm run oseas:audit
npm run oseas:catalog:audit
```

The first checks configured feature assets and their schemas. The catalog audit smoke-checks selected public Earth Engine collections. Neither command ingests data or proves scientific validity.

## Start services locally

Start the API from `osea_data_pipe`:

```powershell
npm run dev
```

Start the frontend in a separate terminal:

```powershell
cd frontend
npm ci
npm run dev
```

The frontend's `VITE_API_PROXY_TARGET` can point the Vite proxy at a local API. No database or Earth Engine credential belongs in the browser. See [`../../frontend/README.md`](../../frontend/README.md).

## Authentication and deployment

In production, OSEAS API requests use a Supabase Auth bearer token by default. The backend verifies tokens using server-side Supabase configuration. `OSEAS_PUBLIC_READ_API=true` is an explicit exception for read-only GET routes; it does not make writes public. In development, auth is optional unless `OSEAS_REQUIRE_AUTH=true`.

The repository-level `render.yaml` describes an API service; frontend deployment is separate. Configure `DB_URL`, Supabase credentials and `CORS_ORIGIN` in the backend host's secret settings. Keep service-role keys and database URLs out of Vercel/browser configuration. Deployment providers may have cold starts or ephemeral filesystems; verify the deployed service behavior rather than assuming local caches are shared.

For command order, optional data workflows and safe recovery, see [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md). For authentication response and route behavior, see [`API_CONTRACTS.md`](API_CONTRACTS.md).

## Common failures

- **Earth Engine authentication failure:** check `GEE_PROJECT_ID`, account permissions, API enablement, and the service-account path if used.
- **Asset missing or denied:** confirm the full `GEE_ASSET_*` value and grant the configured identity read access.
- **Database connection/schema error:** verify the database URL and PostGIS extension, apply the current schema, and run `npm run db:setup`.
- **Partial ingestion:** inspect the run and per-source quality results. Correct invalid geometries or source configuration before treating the inventory as complete.
- **No map evidence:** check source retrieval state, processing-run status, API readiness, and the requested map filters. An empty layer is not automatically a zero-hazard result.
