# Retired Kilimani starter components

The repository is now scoped to OSEAS. The previous Kilimani development-change workflow was removed from the active API and command set.

Removed components include the hard-coded Kilimani AOI and AOI defaults, generated development/case data, old Sentinel-2 construction-change pipeline and model head, detection/case/processing HTTP routes, their controllers and repositories, and legacy training/verification commands.

Shared components retained for OSEAS are:

- `gee/auth.py` for Earth Engine credentials and initialization.
- `src/repositories/db.js` for the PostgreSQL connection pool.
- Express request IDs, structured logging, error handling, CORS, Helmet and rate limiting.
- `config/data_catalog.json` and the OSEAS-specific source, ingestion, spatial, flood and Prithvi modules.

No Kili/Kilimani SQL or sample assessment is used by OSEAS. The only database schema provided is the additive OSEAS schema at [`../database/schema.sql`](../database/schema.sql). The private `.env` was not printed or replaced.

The active project directory is `osea_data_pipe`. Runtime service identity, routes, source configuration and output products are OSEAS-specific; no runtime script depends on the retired `kili-vault-backend` directory name.
