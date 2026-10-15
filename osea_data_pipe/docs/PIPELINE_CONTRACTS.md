# OSEAS pipeline contracts

This document records the actual stage boundaries implemented in the repository. The current orchestrator is `npm run oseas:pipeline`; see [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md) for commands. A stage being callable or having a table does not mean its output is populated or accepted.

## Stage contracts

| Stage / entry point | Inputs and prerequisites | Durable outputs | Acceptance condition |
|---|---|---|---|
| Earth Engine source audit — `npm run oseas:audit` | `GEE_PROJECT_ID`, Earth Engine authentication, configured `GEE_ASSET_*` table IDs. | None; audit only. | Every selected asset is accessible, is a table, and reports usable sample/schema metadata. Audit success does not prove a full ingest. |
| Infrastructure/source ingestion — `npm run oseas:ingest` / `python -m oseas.ingest` | Earth Engine access, DB URL, applied `database/schema.sql`; optional `--datasets` limits source keys. | `energy_assets`, `critical_services`, `administrative_units`, typed asset tables, hydrography/reference tables, `datasets`, `dataset_versions`, `ingestion_runs`, `data_quality_checks`. | All source pages have been fetched and validated; valid records upsert by `(dataset_key, source_feature_id)`, skipped/unusable geometries are counted, run status is terminal and source-level failures are reviewed. |
| Asset/admin assignment — `npm run oseas:assign-admin` | Persisted assets and county/ward geometries. | `asset_admin_assignments` with relation method and clipped length/area where applicable. | Assignment refresh completes; point/line/polygon semantics are correct; assigned/unassigned denominators reconcile against current inputs. |
| UNOSAT reference import — `npm run oseas:flood:unosat:ingest` | Bundled local shapefiles and applied schema. | Source-preserving rows in `flood_reference_features`, dataset/run/version/quality evidence. | Expected files validate; geometries and source keys are checked; source validation caveat remains in provenance. |
| Sentinel-1 flood screen — `npm run oseas:flood:screen -- ...` | Explicit bbox, event and baseline windows, Earth Engine, source inventory; limits and coverage gates documented in the runbook. | Modeled candidate `hazard_events`/`flood_extents`, positive `asset_hazard_exposure`, AOI-limited administrative summaries, model/run/coverage/quality metadata. | Windows and same-orbit inputs are valid; source/valid coverage gates pass; geospatial output is valid and linked to a run. Scientific validation is a separate gate. |
| Prithvi flood inference — `npm run oseas:prithvi:flood -- ...` | Pinned official Sentinel-2 model/checkpoint, Earth Engine scene, <=5 km² AOI, dates, applied schema. | Modeled flood-candidate event, positive intersections, partial AOI-local summaries, model and run artifacts. | Correct six optical channels, clear-pixel and georeferencing checks pass; output is labelled candidate evidence. Kenya accuracy remains unvalidated. |
| CHIRPS event rainfall — `npm run oseas:rainfall` | Dated flood-reference events, county/ward geometries, Earth Engine source access. | `climate_observations` with 30-day totals, absolute/percentage anomaly, source checksum, quality, coverage and run provenance. | Totals/anomalies use correct event/date baseline; null percent change for zero baseline; missing coverage not coerced to zero. This is context, not a flood label. |
| NASA POWER heat — `npm run oseas:heat` | Bounded start/end, NASA POWER availability and existing inventory/administrative data for exposure context. | Climate observations, source version/run metadata, grid events, exposure and administrative summary records. | Daily values and baseline periods/units are recorded; missing periods remain explicit; result is described as coarse near-surface air-temperature exposure, not LST or outage. |
| Black Marble — `npm run oseas:nightlights` | Earth Engine access; a complete-month interval checked against live product availability; inventory/admin/service geometries. | Monthly radiance observations and zone summaries with quality/validity, provenance, source dates and run metadata. | Requested intervals and all zone/month outputs reconcile; true zero remains distinct from missing; complete persisted rows and terminal run are verified. No completed run was found in this audit. |
| FIRMS active fire — `npm run oseas:fire` | Server-side `NASA_FIRMS_MAP_KEY`, Kenya county boundary, sensor/date settings. | Fire point events, source-version/run/coverage metadata and optional asset-proximity exposure. | Response schema/coverage is validated, points are clipped to Kenya, query hash/provenance retained; zero detections are not interpreted as no fire. |
| WorldPop exposure — `npm run oseas:population:persist` | Validated 2024 raster, UNOSAT reference footprints, administrative geometries and schema. | `population_exposure_assessments`, coverage and quality/provenance. | Raster checksum/reference year and valid cell fraction are stored; overlapping features do not double-count cells; no valid cells is unknown, not measured zero. |
| Evidence assessment — `npm run oseas:assessments` | Current assets, assignments, exposure records, verified dependency records, database schema. | Criticality/dependency/vulnerability/resilience dimension rows, county/ward summaries, unranked intervention review candidates, run metadata. | Stable evidence-derived IDs; complete run denominator; unsupported score dimensions remain null/unknown; summary counts reconcile. |
| Read-only API — `/api/v1/oseas/*` | Installed schema, database access; bearer-token verification in production/configured auth. | No writes. Serves current durable rows, catalog, quality and run provenance. | Request validation, filters, pagination, GeoJSON/CRS, error envelope, null/missing states, authorization and layer totals match [`API_CONTRACTS.md`](API_CONTRACTS.md). |

## Canonical database interfaces

- Source inventory: `datasets`, `dataset_versions`, `energy_assets`, `critical_services`, `administrative_units`, `network_lines`, `substations`, `distribution_transformers`, `power_stations`, `mini_grids`.
- Run and quality: `ingestion_runs`, `model_runs`, `data_quality_checks`, `assessment_provenance`, `spatial_coverage_assessments`.
- Evidence: `flood_reference_features`, `hydrography_features`, `climate_observations`, `hazard_events`, `flood_extents`, `fire_events`, `asset_hazard_exposure`, `population_exposure_assessments`.
- Decisions and reporting: `service_dependencies`, `service_dependency_assessments`, `asset_criticality_assessments`, `asset_vulnerability_assessments`, `grid_resilience_assessments`, `administrative_hazard_summaries`, `ward_vulnerability_summary`, `county_vulnerability_summary`, `intervention_scenarios`.

Schema presence is not acceptance evidence. Some records have per-stage provenance, while a universal assessment versioning/quality framework, verified feeder topology, outage history and populated scenario comparisons are still absent.

## Cross-stage acceptance gates

1. A failed source or assessment remains a failed/partial run; it is never an empty-success fallback.
2. Page-level writes and deterministic source keys permit safe retry, but a run is not atomic across all source pages. Consumers must use per-source run status and provenance.
3. Invalid geometry, schema/CRS mismatch and required-input gaps are counted or surfaced; they are not silently converted into zero exposure.
4. Every modelled output is distinguished from source-observed evidence and includes the input period, method/version and limitations.
5. Summaries keep assessed/unknown denominators and valid observation coverage. Uncovered geography is not assigned zero hazard.
6. The API serves only stored outputs and carries run/source/quality metadata; UI claims cannot exceed those API semantics.
7. End-to-end acceptance requires a terminal orchestrator report, read-back of output counts and uniqueness, current source assignments and successful API contract tests. These conditions were not all met at audit time.

See [`PIPELINE_AUDIT.md`](PIPELINE_AUDIT.md) for stage statuses and blockers; [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md) for the six indicator definitions; [`DATA_CATALOG.md`](DATA_CATALOG.md) for source specifics.
