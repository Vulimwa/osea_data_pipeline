# Configure database and Earth Engine access

OSEAS has two separate connections:

- **Processing backend:** connects to Earth Engine and PostgreSQL/PostGIS. It reads source assets, runs processors, and writes derived evidence.
- **Read API:** reads persisted PostGIS records and serves the frontend. Earth Engine credentials are only needed by routes that create live Earth Engine map tiles.

## Credentials and settings

Set values in the backend's ignored local `.env` file or in the backend host's secret manager. Never put them in frontend code or commit them.

| Variable | Use |
| --- | --- |
| `GEE_PROJECT_ID` | Google Cloud project for Earth Engine initialization. |
| `GEE_SERVICE_ACCOUNT_EMAIL`, `GEE_SERVICE_ACCOUNT_KEY_PATH` | Optional service-account authentication. Keep the key file outside the repository. |
| `GEE_ASSET_*` | Full Earth Engine IDs for configured feature-table inputs. |
| `DB_URL` | PostgreSQL/PostGIS connection. `DATABASE_URL` and `SUPABASE_DB_URL` are also accepted. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | API token verification in production. The service-role key stays on the backend. |
| `CORS_ORIGIN` | Allowed frontend origin(s) in production. |
| `OSEAS_PUBLIC_READ_API` | Explicitly permits unauthenticated read-only `GET` requests. |

## Verify access

From `osea_data_pipe`, apply [`../database/schema.sql`](../database/schema.sql) to the intended database, then run:

```powershell
npm run db:setup
npm run oseas:audit
npm run oseas:status
```

The Earth Engine audit checks configured source assets without writing to the database. Ingestion is a separate operation; see [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md).

In production, OSEAS API routes require a Supabase Auth bearer token unless public read access is explicitly enabled. The frontend never needs the direct database URL or service-role key. See [`SETUP.md`](SETUP.md) for deployment details.
