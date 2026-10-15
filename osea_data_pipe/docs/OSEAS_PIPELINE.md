# OSEAS pipeline overview

OSEAS uses the supplied Earth Engine vector assets as its infrastructure source and PostGIS as durable storage. Earth Engine and the database are accessed by backend commands; the frontend does not connect to Postgres.

## Source ingestion

The supplied river, lake and Kenya Nov 2023 flood reference assets are configured as dedicated source types. Apply the additive schema and use `npm run oseas:ingest -- --datasets kenya_rivers,kenya_lakes,kenya_flood_2023_reference` to ingest only those sources. `hydrography_features` and `flood_reference_features` upsert by source key, preserving rerun idempotency and original feature attributes. `--datasets` accepts comma-separated keys so the source-only operation does not reread energy inventory assets.

The bundled 2024 UNOSAT event products are separately handled by `npm run oseas:flood:unosat:audit` (local read-only check) and `npm run oseas:flood:unosat:ingest` (durable import after schema setup). The importer stores the three event flood extent products and Kenya-wide VIIRS maximum extent in `flood_reference_features`, preserving source attributes, per-file checksums and the source's not-yet-validated field status. Source feature keys include the shapefile name and row identifier, so reruns update the same rows. Reference features remain separate from model outputs and hazard exposure assessments.

The historic energy/service/boundary inventory run covered 14 assets. Three additional river, lake and flood-reference table assets are now configured and have passed read-only Earth Engine audit. `npm run oseas:audit` checks configured Earth Engine table access without database writes. `npm run oseas:ingest` reads bounded feature pages, normalizes source types, and batch-upserts deterministic source IDs while persisting run/version/quality metadata.

Tables `energy_assets`, `critical_services`, `administrative_units`, `hydrography_features` and `flood_reference_features` have unique source keys. A Postgres advisory lock prevents competing importer sessions. A restart can leave committed pages; reruns upsert them. `npm run oseas:recover-stale` only changes abandoned run status metadata.

## Dataset registry and retrieval status

`config/data_catalog.json` lists the user-requested satellite/climate/hydrology/event sources with provider, access, coverage, dates, resolution, units, attribution, evidence kind and current adapter status. Catalog entries are not evidence of successful retrieval. Read [`DATA_CATALOG.md`](DATA_CATALOG.md) before selecting a source.

## First hazard workflow

`npm run oseas:flood:screen -- --bbox ... --event-start ... --event-end ... --baseline-start ... --baseline-end ...` runs an explicit small-area Sentinel-1 threshold screen. It uses same-pass VV observations, event/baseline coverage checks, terrain and JRC persistent-water masks, optional mapped-lake masking, and CHIRPS rainfall context. It records the scene footprint and scene coverage fraction separately from unknown per-pixel valid fraction. Results are unvalidated modeled candidates, not observed or confirmed flooding. The script writes bounded vectors, positive asset intersections, provenance, coverage and administrative counts. It does not calculate risk, vulnerability, outage likelihood or resilience scores.

Boundary relationships use `ST_Covers` for point assets and polygon intersections for non-points. Transmission segments are clipped to each ward/county and their per-unit lengths are measured in meters.

## API and model

The OSEAS read-only API is mounted under `/api/v1/oseas`; see [`API_CONTRACTS.md`](API_CONTRACTS.md). `GET /api/v1/oseas/readiness` reports system state without claiming scientific validation. Prithvi is configured with an official Sentinel-2 flood task checkpoint; Kenya accuracy is not validated. See [`MODEL_CARD.md`](MODEL_CARD.md).

## Current run and remaining operator step

The latest observed ingestion run is `5c3d9c73-fb0a-41f6-8b35-c38ee4880021`, not the older 14-source run. It read 17 configured assets and ended `partial`: `kenya_wards` failed when a source `GeometryCollection` reached the target `MultiPolygon` column, and three line-network datasets skipped 148 unusable-geometry features in total. The canonical source-key audit was empty and unique source-key constraints are present. The geometry normalization has now been fixed and unit-tested, but a new live ingestion is required to verify the ward refresh. Previously persisted ward rows were preserved.

No active importer or Black Marble process was found after the interruption. No Black Marble run record exists in PostGIS; the local 2025-06 log/checkpoints represent incomplete local work, not persisted results. Do not treat the acquisition as still running.

The additive schema and core tables are already present, as evidenced by the successful database status query and stored assessment/source results. `database/schema.sql` remains safe to reapply if a later schema check finds missing objects; follow it with `npm run db:setup`. Reference flood features and modeled candidates use distinct evidence types and map endpoints. Reported ADAM area/population are stored separately from geometry-measured area; ingesting reference data alone does not validate a model or create a risk score. `GET /api/v1/oseas/layers/{output}/geojson` reads stored climate, terrain, land-cover, fire, asset, dependency, coverage, population, resilience, summary and intervention outputs; an empty/unpopulated product remains `not_assessed`.

For the interruption-safe recovery sequence and conditions for starting a new processing run, see [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md).

See [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md) for the complete setup and execution sequence and [`INTEGRATION_READINESS.md`](INTEGRATION_READINESS.md) for the current readiness decision.
