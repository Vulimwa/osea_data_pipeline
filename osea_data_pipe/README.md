# OSEAS

OSEAS is a climate-risk and energy-infrastructure evidence pipeline for Kenya. It brings together infrastructure inventories, administrative boundaries, climate observations and hazard evidence; stores traceable spatial outputs in PostgreSQL/PostGIS; and serves them to a read-only API and interactive map.

The application is designed for screening and investigation. It reports evidence, coverage and missing inputs rather than turning unknowns into zero risk. It does not currently provide a validated national grid-failure probability or outage forecast.

## Repository layout

- `oseas/`, `scripts/`, `gee/`: Python ingestion, source adapters, raster workflows, geospatial assessments and orchestration.
- `src/`: Express API, validation, authentication and database access.
- `database/schema.sql`: additive OSEAS database schema.
- `config/data_catalog.json`: source metadata and retrieval state.
- `frontend/`: React application and ArcGIS Maps SDK map.
- `docs/`: architecture, setup, data, methods, models, API and operational guidance.

## Quick start

The backend and frontend are separate applications. For backend setup and secure configuration, start with [`docs/SETUP.md`](docs/SETUP.md). For the pipeline sequence, see [`docs/END_TO_END_RUNBOOK.md`](docs/END_TO_END_RUNBOOK.md).

Typical backend checks from this directory:

```powershell
npm ci
python -m pip install -r requirements.txt
npm run db:setup
npm run oseas:audit
npm run oseas:status
```

These commands do not install the schema: apply [`database/schema.sql`](database/schema.sql) to the intended PostGIS database first. A full pipeline run can take a long time and should not be started casually; review its prerequisites in the runbook.

Run the API locally with `npm run dev`. The API is mounted under `/api/v1/oseas`; start with `/api/v1/oseas/readiness`.

To run the map application, follow [`../frontend/README.md`](../frontend/README.md).

## Documentation

Read in this order:

1. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system components and data flow.
2. [`docs/DATA_CATALOG.md`](docs/DATA_CATALOG.md) — source families and how to interpret retrieval state.
3. [`docs/ASSESSMENT_METHODS.md`](docs/ASSESSMENT_METHODS.md) and [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) — implemented calculations, prototype scoring and limitations.
4. [`docs/SETUP.md`](docs/SETUP.md) and [`docs/END_TO_END_RUNBOOK.md`](docs/END_TO_END_RUNBOOK.md) — configuration and execution.
5. [`docs/PIPELINE_CONTRACTS.md`](docs/PIPELINE_CONTRACTS.md) and [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md) — stage outputs and API response contracts.
6. [`docs/FRONTEND_INTEGRATION_GUIDE.md`](docs/FRONTEND_INTEGRATION_GUIDE.md) — map integration and API usage.

[`../outputs.md`](../outputs.md) is the concise description of project scope and deliverables.

## Validation

`npm test` runs the backend JavaScript unit tests. `npm run test:oseas` runs the Python tests. `npm run lint` checks the backend TypeScript and `npm run build` bundles the API. These local checks do not prove that live source credentials work, that a database is complete, or that a model is scientifically validated.
