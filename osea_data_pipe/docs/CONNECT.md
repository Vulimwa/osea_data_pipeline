# Connect OSEAS to Supabase and Earth Engine

Follow [`SETUP.md`](SETUP.md) for environment setup, manual schema application, Earth Engine audit and PostGIS ingestion.

The OSEAS importer uses a PostgreSQL connection URL (`DB_URL`, `DATABASE_URL`, or `SUPABASE_DB_URL`) and Earth Engine credentials. It does not use the Supabase service role key for direct SQL access. The OSEAS API uses that server-side key only to verify Supabase Auth bearer tokens in production. The private asset registry is configured by `GEE_ASSET_*` variables in `.env`.

The service API is OSEAS-specific. It reads the OSEAS PostGIS products and exposes them under `/api/v1/oseas`; the previous Kilimani endpoints are no longer mounted.
