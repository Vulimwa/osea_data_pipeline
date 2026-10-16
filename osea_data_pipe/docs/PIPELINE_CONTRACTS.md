# Pipeline stages and acceptance

A stage is accepted only when its prerequisites are met, its run reaches a terminal state, and its output passes the checks listed below. Having a command, table, route or catalog entry does not prove that usable data exist.

## Stage contracts

| Stage | Entry point | Main outputs | Acceptance checks |
| --- | --- | --- | --- |
| Database setup | Apply `database/schema.sql`; `npm run db:setup` | OSEAS PostGIS schema and connectivity report | Required tables/extensions are present and API/database connections work. The check command does not apply schema. |
| Source audit | `npm run oseas:audit` | Audit report only | Configured assets are accessible, expected types/geometries and usable properties are confirmed. No database writes. |
| Catalog audit | `npm run oseas:catalog:audit` | Bounded source smoke-check report | Selected source is accessible for the checked place/date and expected bands are present. This does not establish full spatial/temporal coverage or persist data. |
| Inventory ingestion | `npm run oseas:ingest` | Source inventory, dataset versions, ingestion runs and quality checks | Every source has a terminal status; valid features are upserted by stable identifiers; skipped geometries and partial results are reviewed. |
| Administrative assignment | `npm run oseas:assign-admin` | Asset-to-county/ward assignments | Current boundaries exist; assigned/unassigned totals and spatial relation methods are reviewed. |
| CHIRPS summaries | `npm run oseas:rainfall` | Event-window rainfall totals/anomalies and provenance | Event dates, baseline window, unit, valid image coverage and reporting-unit results reconcile. |
| NASA POWER heat | `npm run oseas:heat` | Daily observations, baseline comparisons and supported exposure summaries | Period, variable, units, baseline and grid coverage are recorded; output remains coarse-air-temperature context. |
| VIIRS nighttime radiance | `npm run oseas:nightlights` | Quality-aware monthly radiance summaries | Full month selection, quality mask, valid observations, tile coverage, periods and persisted run are confirmed. |
| FIRMS fire | `npm run oseas:fire` | Active-fire events and optional proximity evidence | API response and date/sensor scope are recorded; returned points are clipped to Kenya. A zero count is not proof of no fire. |
| WorldPop exposure | `npm run oseas:population:persist` | Population estimates within reference footprints and administrative intersections | Raster checksum/year, geometry fingerprint, valid-cell fraction and duplicate-cell handling are checked. |
| Flood screen | `npm run oseas:flood:screen` | Candidate polygons, positive asset intersections and bounded summaries | Event/baseline windows, orbit, coverage, masks, geometry and provenance pass. Candidate output remains unvalidated evidence. |
| Prithvi inference | `npm run oseas:prithvi:flood` or `npm run oseas:prithvi:national` | Bounded candidate polygons or nationwide admin pixel summaries | Correct checkpoint/input bands and tile/coverage handling are verified. Kenya accuracy remains unvalidated. |
| Evidence assessment | `npm run oseas:assessments` | Asset, dependency, criticality, vulnerability, resilience and admin summary records | Run denominators reconcile; missing inputs remain explicit; unsupported numeric scores stay null/withheld. |
| Read API | `/api/v1/oseas/*` | Read-only JSON and GeoJSON responses | Validation, pagination, status, CRS, auth and provenance match [`API_CONTRACTS.md`](API_CONTRACTS.md). |

## Persistence and retry behavior

Inventory and many derived outputs use stable keys and idempotent upserts. Rerunning a stage should reconcile the same inputs rather than duplicate them, but it does not necessarily delete rows that are no longer present upstream. Inspect the stage's run and source-version records to understand what changed.

Page-level writes may leave committed pages when a later page fails. A `partial` run must be reviewed at the source/stage level before downstream processing. Do not assume earlier successful rows make a failed stage complete.

## Coverage and interpretation gates

1. Failed credentials, missing sources, invalid periods and schema errors must surface as failed or blocked stages, not empty success.
2. Partial spatial or temporal coverage must remain visible in result status and provenance.
3. Unknown or unassessed areas are not assigned zero hazard.
4. Hazard candidates, observations, exposure records and assessment interpretations remain separate evidence types.
5. A geometry intersection does not establish asset condition, network connectivity or service dependency.
6. Production composite scores remain withheld when supported inputs or validation are missing.
7. Every presentation of a result should identify its source period, method and current processing status.

The `intervention_scenarios` records currently represent evidence-led candidates for review, not modeled intervention effects. Scenario/CAT impact calculations are a proposed extension; see [`SCENARIO_CAT_MODEL.md`](SCENARIO_CAT_MODEL.md).

## Storage interfaces

Core source and output tables include `energy_assets`, `critical_services`, `administrative_units`, `network_lines`, `datasets`, `dataset_versions`, `ingestion_runs`, `data_quality_checks`, `hazard_events`, `flood_extents`, `climate_observations`, `asset_hazard_exposure`, `population_exposure_assessments`, `service_dependency_assessments`, `asset_criticality_assessments`, `asset_vulnerability_assessments`, `grid_resilience_assessments`, administrative summary tables and `intervention_scenarios`. The complete schema is in [`../database/schema.sql`](../database/schema.sql).
