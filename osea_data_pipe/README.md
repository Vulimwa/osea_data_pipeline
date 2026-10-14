# OSEAS Climate Risk and Energy Infrastructure Pipeline

OSEAS reads the supplied Kenya energy-infrastructure assets from Earth Engine, writes durable records to PostgreSQL/PostGIS, and exposes read-only map/API endpoints.

## Implemented components

- Paged, batched, idempotent infrastructure ingestion with a single-writer lock and page-level progress.
- Shared registry of the requested satellite, climate, terrain, fire, flood-reference and supporting datasets, with honest per-source retrieval states.
- Additive PostGIS schema for source provenance, source-preserving rivers/lakes and flood-reference polygons, spatial coverage, assets, exposure, summaries, population-exposure and grid-resilience records.
- Bounded Sentinel-1 and Prithvi flood-candidate workflows with JRC and configured lake masks; the Prithvi model still receives only its six expected Sentinel-2 channels.
- Map-ready GeoJSON routes for stored climate, terrain, fire, exposure, vulnerability, dependency, coverage, population, resilience, summary and intervention outputs.
- Verified Global Wind Atlas country GeoTIFF cache and resource-layer endpoints.
- Read-only OSEAS API and readiness routes under `/api/v1/oseas`.
- Prithvi results remain unvalidated for Kenya until compared with held-out local reference extents.

The flood method is an unvalidated candidate screen, not confirmed inundation or a calibrated risk score. Climate, heat, wildfire, vulnerability, service reliability and resilience products remain unassessed until data and methods are implemented and validated.

## Setup

1. Install dependencies: `npm ci` and `python -m pip install -r requirements.txt`.
2. Configure `.env` using placeholders in `.env.example`; never commit secrets.
3. Apply [`database/schema.sql`](database/schema.sql) in Supabase SQL Editor, then run `npm run db:setup`.
4. Check source access with `npm run oseas:audit` and `npm run oseas:catalog:audit`.
5. When setup is complete, ingest infrastructure with `npm run oseas:ingest` and monitor using `npm run oseas:status`.
6. After a completed source run, use the bounded flood command documented in [`docs/END_TO_END_RUNBOOK.md`](docs/END_TO_END_RUNBOOK.md).

## Documentation

- [`docs/DATA_CATALOG.md`](docs/DATA_CATALOG.md): public sources, access, metadata and validation state.
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md): flood method and Prithvi status.
- [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md): stable read-only endpoints and GeoJSON format.
- [`docs/INTEGRATION_READINESS.md`](docs/INTEGRATION_READINESS.md): evidence-based integration status.
- [`docs/END_TO_END_RUNBOOK.md`](docs/END_TO_END_RUNBOOK.md): reproducible commands and troubleshooting.

## Verification

`npm test`, `npm run test:oseas`, `npm run lint`, and `python -m compileall -q oseas scripts tests/python` run local tests/checks. Live Earth Engine and database output acceptance requires authenticated credentials and is reported separately from unit tests.
