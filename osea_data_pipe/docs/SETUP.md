# OSEAS developer setup

## Prerequisites

- Node.js 20+ and npm.
- Python 3.10+.
- A Supabase/PostgreSQL connection URL with PostGIS enabled.
- Earth Engine access to each configured table asset, and a Cloud project enabled for Earth Engine.

## Installation

From the backend project directory:

```powershell
npm ci
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set the real values in `.env`. For service-account authentication, set `GEE_SERVICE_ACCOUNT_EMAIL` and a readable `GEE_SERVICE_ACCOUNT_KEY_PATH`. Keep the key file outside source control. If using user credentials, authenticate Earth Engine through the normal `earthengine authenticate` flow and leave the key path empty.

The asset references supplied for OSEAS were added to the private `.env` as `projects/osea-hack/assets/osea/<asset>`. Run the audit to verify these exact IDs and replace any that do not resolve. `GEE_PROJECT_ID` controls Earth Engine initialization; do not assume it is the same project that owns the assets.

For NASA sources, `NASA_FIRMS_MAP_KEY` holds the server-side FIRMS key. Latest-day ingestion defaults to `VIIRS_SNPP_NRT`; the request envelope comes from ingested Kenya county boundaries, and detections are filtered to their exact union. Leave both `OSEAS_FIRE_START_DATE` and `OSEAS_FIRE_END_DATE` empty for the latest day, or set both for historical data. Run `npm run oseas:fire` to update fire evidence without repeating other pipeline stages. Black Marble accepts `LAAD_TOKEN_NASA` as the NASA Earthdata token alias (or `NASA_EARTHDATA_TOKEN`).

## Database

Open [`../database/schema.sql`](../database/schema.sql) and run it in Supabase SQL Editor. This is the only schema installation step. It creates OSEAS tables and indexes additively and does not delete old or unrelated database objects.

Then check connection and table presence:

```powershell
npm run db:setup
```

The script performs a read-only check. It does not apply schema or migrate legacy data. Python accepts `DB_URL`, `DATABASE_URL`, or `SUPABASE_DB_URL`. Use the Postgres connection URL rather than the Supabase service role key for direct PostGIS writes.

The OSEAS API requires a Supabase Auth bearer token in production. Keep `SUPABASE_SERVICE_ROLE_KEY` on the backend only; it is used only to validate access tokens through Supabase Auth. Set `OSEAS_REQUIRE_AUTH=true` to enforce the same check during development. Do not expose the service-role key to a browser or client app.

## Earth Engine audit and ingestion

```powershell
npm run oseas:audit
npm run oseas:ingest
```

Audit validates the configured assets and emits a JSON report without writing to PostGIS. Ingestion persists source rows in bounded pages and writes run, dataset version, and quality-check metadata. Missing optional assets are logged while other assets continue. The command exits `0` when all sources succeed, `2` for a partial run, and `1` when all sources fail or setup cannot start.

## Tests

`npm test` runs JavaScript unit tests. `npm run test:oseas` runs isolated Python tests. `npm run lint` and `npm run build` check the API build. For current implementation limits and live checks, see [`INTEGRATION_READINESS.md`](INTEGRATION_READINESS.md).

## Common failures

- **Authentication failure:** check `GEE_PROJECT_ID`, account permissions, key path, and the Earth Engine API enablement.
- **Asset not found/access denied:** correct the related `GEE_ASSET_*` full ID and grant the service account read access.
- **PostGIS/schema failure:** apply `database/schema.sql` in Supabase and check that the connection URL points to the OSEAS database.
- **Geometry insert failure:** inspect the reported asset geometry; the importer expects a valid vector geometry convertible from GeoJSON.
- **Partial ingestion:** rerun after correcting the source problem. Stable source identifiers and database uniqueness constraints make repeats idempotent.
