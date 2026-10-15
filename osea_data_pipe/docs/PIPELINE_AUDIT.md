# OSEAS pipeline audit

Assessment date: 2026-10-15. This is the initial gap report, recorded before the ingestion code change below. It distinguishes stored evidence from configured sources and runnable code.

## Executive status

**Overall status: `BLOCKED`.** Existing partial evidence and read-only API routes are available, but the latest inventory ingestion failed for Kenya ward boundaries, the national Black Marble run has no completed database record, and a complete current all-stage pipeline run is not verified.

No ingestion, assessment, schema migration, or other database write was run during this audit. The latest database status was retrieved with `npm run oseas:status`; additional database checks were read-only `SELECT`s. The Windows process list, lock metadata and logs were also inspected. Both saved lock-owner PIDs were dead and no matching acquisition process was running. Lock files were left untouched.

## Actual pipeline map

```text
Earth Engine vector assets
  -> python -m oseas.ingest
     -> page-level PostGIS upserts + ingestion run/version/quality records
  -> scripts/assign_assets_admin.py
     -> asset_admin_assignments (point coverage; clipped line/polygon measures)
  -> source-specific acquisition and evidence stages
     -> flood candidates, rainfall, heat, active-fire, population, night-lights
  -> scripts/run_evidence_assessments.py
     -> per-asset evidence dimensions + county/ward summaries + unranked review candidates
  -> read-only Express API under /api/v1/oseas
```

The orchestrator is `npm run oseas:pipeline` (`scripts/run_oseas_pipeline.py`). It takes a local process lock, prints stage results, verifies Black Marble completion against database rows, and writes `outputs/last_pipeline_run.json`. That report does not currently exist in this workspace. Individual persisted source/assessment results exist, but the full chain has not been verified in one current run. The frontend is unchanged and not integrated with the complete OSEAS workflow.

## Pipeline acceptance matrix

| Stage | Status | Verified evidence | Limitation / next dependency |
|---|---|---|---|
| Source registry | `PARTIAL` | `config/data_catalog.json` is shared by Python audit and the API; catalog entries state retrieval and access. | Some entries are only identified or require product/access selection. Catalog presence is not a successful retrieval. |
| Earth Engine inventory ingestion | `FAIL` | Latest run `5c3d9c73-fb0a-41f6-8b35-c38ee4880021` is terminal `partial`, with 17 configured assets, one failed asset and 148 geometry skips. It retained per-source counts and quality details. | The `kenya_wards` collection contained a `GeometryCollection`, which the `MultiPolygon` destination rejected. Fix is unit-tested but not yet verified by a live rerun. |
| Source geometry skips | `PARTIAL` | The latest run counted `transmission_lines_132kv` (1), `transmission_lines_33kv` (139) and `unidentified_grid_network` (8) unusable geometries. | These 148 source records remain unpersisted; their source geometry/record quality needs review. |
| Duplicate prevention | `PASS` for checked inventory keys | `npm run oseas:status` found no duplicate asset, service or administrative source keys and found unique source-key constraints. | This check is not a universal duplicate audit over every derived output table. |
| PostGIS schema and provenance | `PARTIAL` | The status command queried the installed inventory, run and quality tables successfully. Schema defines source versions, run records, quality checks, coverage, hazard/exposure and summary records. | A schema existing does not prove every result is fresh, complete or scientifically valid. Latest failed ward refresh left prior ward rows in place. |
| Asset/admin assignment | `PARTIAL` | Existing evidence records 193,390 ward/county assignments for 101,989 assets; 101,939 assets were assigned. | 50 assets were unassigned; refresh after successful boundary ingestion is required. |
| Flood candidate workflows | `PARTIAL` | Bounded Sentinel-1 and Prithvi pilots are documented with persisted candidate products, source/method provenance and AOI-local summaries. | The products are unvalidated candidates, not confirmed flood extents or calibrated risk. Small pilot AOIs do not support national claims. |
| Rainfall context | `PARTIAL` | CHIRPS run `fdc303fc-7f11-4353-9e30-e8c262205ddc` persisted 7,878 observations for two dated 2024 reference events across 1,313 county/ward units. | Event-window totals/anomalies are not an independent flood validation or a complete extreme-rainfall product. |
| Heat context | `PARTIAL` | NASA POWER T2M_MAX processing and asset/admin outputs are persisted for 2024, with source-version provenance. | Coarse near-surface air temperature is not land-surface temperature, equipment temperature, damage, or outage likelihood. |
| Night-time lights | `BLOCKED` | A read-only database query found no `oseas_viirs_black_marble` run. The local log last reached 2025-06, month 23/36 and 80,000/151,317 zones; checkpoints existed through 2025-05. Saved lock owners were not alive and no matching local process was found. | Resume only after credentials are rotated and the period is rechecked against the live source manifest. No complete result rows are verified. |
| Active fire | `PARTIAL` | FIRMS run `5f1ab0a9-c090-435a-899b-9c6df0e27a74` recorded a latest-day Kenya query and coverage/provenance. | The query returned zero detections; that is not proof of no fire. There are no burned-area/perimeter or asset-damage outputs. |
| Population context | `PARTIAL` | WorldPop 2024 raster and event/administrative population-exposure processing are documented with checksum and coverage. | Modeled people inside reference footprints are not observed impacts or populations served by an asset. |
| Evidence assessments | `PARTIAL` | Prior national run `edabcb94-a39c-4513-91de-851148d07df3` persisted 101,989 per-asset dimensions, 1,274 ward and 47 county summaries, and 10,529 unranked field-review candidates. | The current administrative input refresh is incomplete; national criticality, vulnerability and resilience composites remain withheld. |
| Read-only API | `PARTIAL` | Authenticated OSEAS route definitions, filtering, pagination, GeoJSON, run/source metadata and explicit missing-data states exist. | A route or table is not proof of a current layer. No end-to-end frontend integration was verified. |
| Frontend workflow | `NOT_IMPLEMENTED` | A backend integration guide exists. | The OSEAS map-centric frontend workflow is explicitly deferred. |
| All-stage orchestration | `FAIL` | The orchestrator and run-report implementation exist. | No `outputs/last_pipeline_run.json` exists and a current full pipeline run was not verified. |

## Six organizer indicators

| Indicator | Status | Actual output | Main limitation |
|---|---|---|---|
| Flood Risk Exposure | `PARTIAL` | Bounded Sentinel-1 threshold candidates and Prithvi optical flood/water candidates; positive asset intersections and partial local summaries. | Not independently validated for Kenya; candidate extent is not calibrated risk; pilot extents are localized. |
| Heat Stress Risk | `PARTIAL` | NASA POWER daily T2M_MAX, monthly-baseline anomaly/hot-day context and nearest-grid asset screen. | Coarse air-temperature exposure is not LST or equipment/service-impact evidence. |
| Wildfire Exposure | `PARTIAL` | FIRMS active-fire point detections and optional distance-based asset context. | No burned-area/perimeter product; zero detection is not no fire; proximity is not asset impact. |
| Infrastructure Criticality | `PARTIAL` | Evidence-gated records and missing-input status. | National numeric score is deliberately withheld without topology, served load and redundancy evidence. |
| Service Reliability Risk | `NOT_IMPLEMENTED` | No outage/reliability estimator or reliability score is produced. | Requires verified network topology and outage/failure/restoration history; hazard exposure alone is not reliability risk. |
| Grid Resilience Scores | `PARTIAL` | Per-asset evidence dimensions, with unknown redundancy/topology/outage dimensions explicit. | Composite score is withheld; the current records are not a numeric resilience score. |

## Initial blockers and risk register

1. **Ward geometry mismatch:** the source contains a `GeometryCollection` but `administrative_units.geom` requires `MultiPolygon`. The original importer sent the collection directly to PostGIS, failed the entire ward source, and left prior rows untouched.
2. **Interrupted Black Marble acquisition:** no local process or database run is active/complete. Checkpoints/logs only evidence partial work. The output is not yet persisted.
3. **Partial source completeness:** 148 unusable line geometries and 50 assets without an administrative assignment remain evidence gaps.
4. **No single reproducible all-stage run:** older verified stage runs do not constitute a fresh end-to-end acceptance run.
5. **Scientific limits:** flood candidates lack Kenya accuracy metrics; heat, active-fire and population products are contextual screens; reliability/topology evidence is missing; composite criticality/vulnerability/resilience scores and intervention benefits are withheld.
6. **Frontend readiness:** API capabilities exist, but a working UI consuming the source, quality, coverage and run provenance was not tested.

## Safe code change and verification

The first root-cause fix was made in `oseas/ingest.py`: county/ward GeometryCollections now retain only Polygon/MultiPolygon members before insertion, and collections without polygonal members use the existing skip counter. Rivers/lakes preserve their source GeometryCollections. Two regression tests prove the extraction and skip cases.

The focused ingestion tests pass (12 tests). The complete Python OSEAS tests, Node unit tests, TypeScript check and Python byte-compilation also pass. No database rows were changed by this fix. The database still needs a new ingestion run before the ward source can be marked passing.

## Dependency-ordered next work

1. Rotate the exposed database credential, update the local environment without printing it, and verify Earth Engine/DB access.
2. Re-run source audit, then ingestion; confirm the ward source is successful and inspect the 148 remaining line skips.
3. Refresh administrative assignments and verify counts/reconciliation.
4. Resume/finish Black Marble from checkpoints only after live source-period verification; verify full persisted row counts and run status.
5. Run the configured single pipeline after preceding gates pass; inspect `outputs/last_pipeline_run.json` and all stage outcomes.
6. Validate flood candidates against aligned held-out local references; implement and validate missing wildfire/LST/drainage/reliability evidence before promoting those outputs.
7. Integrate and test frontend flows for layer discovery, assessment evidence, coverage, run history and missing states.

For exact commands, recovery conditions and acceptance checks see [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md). Stage I/O contracts are in [`OSEAS_PIPELINE.md`](OSEAS_PIPELINE.md) and the linked acceptance detail in [`PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md). Source specifics remain in [`DATA_CATALOG.md`](DATA_CATALOG.md); API details remain in [`API_CONTRACTS.md`](API_CONTRACTS.md).
