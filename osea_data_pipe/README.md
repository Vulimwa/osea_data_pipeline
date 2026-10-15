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

Flood candidates are screening evidence, not confirmed inundation or a calibrated risk score. Some climate, heat, fire and population evidence has been processed, but those products have limited periods/coverage and are not equivalent to a validated national risk assessment. Composite criticality, service-reliability and resilience scores are withheld when required operational evidence is missing.

## Setup

1. Install dependencies: `npm ci` and `python -m pip install -r requirements.txt`.
2. Configure `.env` using placeholders in `.env.example`; never commit or paste secrets. Rotate any credential that has been exposed before running commands that write to the database.
3. Apply [`database/schema.sql`](database/schema.sql) in Supabase SQL Editor, then run `npm run db:setup`.
4. Check source access with `npm run oseas:audit` and `npm run oseas:catalog:audit`.
5. After credential rotation and the read-only checks, run the dependency-ordered, non-destructive pipeline with `npm run oseas:run`.
6. Inspect `outputs/last_pipeline_run.json`, `npm run oseas:status`, and the read-only layers under `/api/v1/oseas`.

The 2026-10-15 audit found the latest ingestion run terminal `partial` (one source failed); it was not still processing. The ward-geometry fix is unit-tested, but the database has not been refreshed with it. For the safe recovery and verification sequence, use the “Recovery after an abrupt shutdown” section in the runbook before starting downstream processing.
The single command preserves existing rows and uses source-key upserts. It does not run `clean`, stale-run recovery, or local image workflows by default. The optional Kano demo is an API-only filter over the separate published pilot (`sourceDataset=osm_kano_pilot` and its bbox); it does not narrow or replace nationwide processing. The requested indicator/output checklist is in [`../outputs.md`](../outputs.md); report stages that are unsupported or blocked remain explicit rather than being marked complete.

## Documentation

- [`docs/PIPELINE_AUDIT.md`](docs/PIPELINE_AUDIT.md): evidence-backed baseline, stage status, blockers and organizer indicator matrix.
- [`docs/PIPELINE_CONTRACTS.md`](docs/PIPELINE_CONTRACTS.md): actual stage inputs, outputs, dependencies and acceptance gates.
- [`docs/ASSET_AUDIT.md`](docs/ASSET_AUDIT.md): historical audit of the original 14 Earth Engine assets; later source additions are tracked in the data catalog.
- [`docs/DATA_CATALOG.md`](docs/DATA_CATALOG.md): public sources, access, metadata and validation state.
- [`docs/ASSESSMENT_METHODS.md`](docs/ASSESSMENT_METHODS.md): indicator methods, missing-data behavior and limitations.
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md): flood method and Prithvi status.
- [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md): stable read-only endpoints and GeoJSON format.
- [`docs/INTEGRATION_READINESS.md`](docs/INTEGRATION_READINESS.md): evidence-based integration status.
- [`docs/END_TO_END_RUNBOOK.md`](docs/END_TO_END_RUNBOOK.md): reproducible commands and troubleshooting.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md): current implementation status and verified run evidence.

## Verification

`npm test`, `npm run test:oseas`, `npm run lint`, and `python -m compileall -q oseas scripts tests/python` run local tests/checks. Live Earth Engine and database output acceptance requires authenticated credentials and is reported separately from unit tests.
