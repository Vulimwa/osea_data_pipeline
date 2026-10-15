# OSEAS backend implementation status

Assessment date: 2026-10-15. Status reflects code and observed results; configured sources and runnable processors are not represented as persisted data.

## Initial audit snapshot (before code changes)

Overall baseline: `BLOCKED` for a complete, refreshed national assessment. Existing persisted results and the read-only API remain useful with limitations, but the latest source-ingestion run did not complete all configured inputs and there is no verified completed all-stage pipeline report.

This snapshot was established read-only on 2026-10-15 using `npm run oseas:status`, database SELECTs, local process/lock inspection, and the checked-in code and tests. No ingestion, assessment, database migration, or output-writing command was run during the audit.

| Pipeline stage | Baseline status | Evidence |
|---|---|---|
| Source registry | `PARTIAL` | `config/data_catalog.json` describes multiple Earth Engine, NASA, Copernicus, and WorldPop sources. Several are catalog-only or lack a complete acquisition-to-persistence workflow; a registry entry is not retrieval evidence. |
| Core Earth Engine ingestion | `FAIL` | Latest database run `5c3d9c73-fb0a-41f6-8b35-c38ee4880021` ended `partial` at 2026-10-15 02:12:39 UTC, with 17 configured assets, one failed asset, and three assets with geometry skips. |
| Ward boundary refresh | `FAIL` | `kenya_wards` failed with `Geometry type (GeometryCollection) does not match column type (MultiPolygon)`. A read-only count found 1,274 existing ward rows and zero rows stamped with the latest run ID; prior rows were not deleted. |
| Geometry skips | `PARTIAL` | The latest run recorded 148 skipped features: `transmission_lines_132kv` (1), `transmission_lines_33kv` (139), and `unidentified_grid_network` (8). These were counted, but the source features still require review. |
| Duplicate prevention | `PASS` for checked inventory keys | `npm run oseas:status` returned no duplicate source keys and found unique source-key constraints on assets, services, and administrative units. No claim is made about unrelated assessment IDs. |
| Hazard and contextual products | `PARTIAL` | Existing run evidence is documented for bounded flood candidates, POWER heat, CHIRPS event rainfall, FIRMS detections, and WorldPop exposure. These have limited spatial/temporal scope and scientific validation gaps; they are not a complete national hazard suite. |
| Black Marble nighttime lights | `BLOCKED` pending a safe resume | No `oseas_viirs_black_marble` run rows were found. The last local log shows 2025-06 at month 23/36 and 80,000/151,317 zones; checkpoint files are present only through 2025-05. The VIIRS lock PID (15068) and orchestrator lock PID (5488) were not alive, and no matching local processing process was found. The lock files were left untouched. |
| Evidence assessments and reporting | `PARTIAL` | Prior national output counts and withheld-score behavior are documented below, but a fresh all-stage run was not verified in this audit. Ward coverage remains stale relative to the latest failed ingestion. |
| API and frontend integration | `PARTIAL` | Read-only routes and API contracts exist. The API routes are implemented, but this audit did not verify a live frontend workflow against all layers; frontend integration remains deferred. |
| End-to-end orchestration | `FAIL` | No `outputs/last_pipeline_run.json` exists. A single, current all-stage run with complete outputs has not been verified. |

The ingestion importer commits bounded pages and upserts by source key, so already committed records remain available after a later page/source failure. This is safe for reruns, but means a failed source can leave a mixture of previously stored and newly refreshed rows; consumers must use run provenance and source-level status rather than treating the inventory as a single atomic snapshot.

The baseline gap requiring the first fix was the ward `GeometryCollection` mismatch. The normalization fix now passes regression tests; the next operational gate is to rotate any exposed database credential, confirm no competing writer is active, and rerun ingestion. No live ingestion was started by this audit.

## Changes made after the baseline

- Updated `oseas/ingest.py` to extract polygon and multipolygon members from a ward/county `GeometryCollection` before writing to the canonical `MultiPolygon` column. Geometry collections without polygonal members now follow the existing skipped-geometry accounting path. Rivers and lakes retain their source geometry-collection behavior.
- Added two regression tests for polygon extraction and non-polygon collection skips. The focused `test_oseas_ingest.py` suite passes (12 tests).
- The live database was not modified or rerun. The latest run remains `partial`; the 1,274 existing ward records still have zero rows stamped by that run. A rerun is required to verify refreshed ward persistence.
- The 148 unusable line-feature geometries remain source data gaps. They are still explicitly counted and skipped; no source feature has been fabricated or replaced.

| Deliverable | Status | Evidence and remaining limitation |
|---|---|---|
| 59 Standardized energy inventory | READY_WITH_LIMITATIONS | Earth Engine ingestion, normalization, deterministic source keys, PostGIS upserts and county/ward assignment exist. Historic run recorded rejected geometries; configured data is not proof of national completeness. |
| 60 Flood extent | READY_WITH_LIMITATIONS | UNOSAT run `f7ca7842-711f-4840-8037-04abc337448e` retained 4 unique reference polygons. The bounded Nairobi/Kiambu Sentinel-1 run `ad681824-b47d-4dad-8478-fdd5a3dce028` completed with 100% scene-footprint coverage, 1 candidate polygon, 4 local administrative summaries and 0 energy-asset intersections. Prithvi run `49910391-e43b-4bf6-8cd9-fadc737ce709` completed from the 2024-05-02 Sentinel-2 scene, producing 3 connected candidates unioned into one MultiPolygon event; 4 local summaries were partial and 0 energy assets were in the 4.92 km2 AOI. Both model outputs are unvalidated. No accuracy metric is claimed. |
| 61 Rainfall indicators | READY_WITH_LIMITATIONS | CHIRPS run `fdc303fc-7f11-4353-9e30-e8c262205ddc` persisted 7,878 deterministic observations across 1,313 county/ward units for 2 dated flood events: 30-day totals, absolute anomalies and percentage anomalies where the baseline is positive. Quality checks, source version and run provenance are present. Query `/api/v1/oseas/layers/rainfall/geojson`. Extreme-rainfall thresholds and independent Kenya validation remain outstanding. |
| 62 Terrain/drainage | READY_WITH_LIMITATIONS | DEM slope is used by Sentinel-1 screening. A reusable terrain/drainage product, flow accumulation and asset association have not been executed. |
| 63 Heat exposure | READY_WITH_LIMITATIONS | NASA POWER daily T2M_MAX, provider monthly-climatology anomalies, hot-day screens, grid-cell events, source versions and nearest-cell asset screening completed for 2024. Live run `e65d4f92-39a4-4b7e-aae3-49c7cbd05440` has 215,208 daily/climatology observations, 294 grid cells, 101,987 asset exposure rows and 1,261 ward/county summaries. Coarse (~0.5-degree) air temperature is not Landsat LST; this is hazard exposure context, not asset damage or outage evidence. |
| First-class night-lights context | PARTIAL | NASA VIIRS Black Marble VNP46A2 has a quality-screened, resumable adapter for monthly summaries. No `oseas_viirs_black_marble` run rows were found. At audit time, the last log showed 2025-06 at month 23/36 and 80,000/151,317 zones; local checkpoints existed through 2025-05. The recorded local lock owners were not alive, so the job was not considered active. A source-manifest-verified complete interval and persisted database output are still required. |
| 64 Wildfire | READY_WITH_LIMITATIONS | FIRMS run `5f1ab0a9-c090-435a-899b-9c6df0e27a74` successfully queried latest-day `VIIRS_SNPP_NRT`, persisted valid Kenya coverage/provenance, and returned zero active detections for 2026-10-14. Zero returned detections is not evidence of no fire. The adapter does not produce fire perimeters, burned area or damage claims. |
| 65 Asset hazard exposure | READY_WITH_LIMITATIONS | Existing flood exposure and new heat/fire proximity routines persist asset-linked measurements. Complete source-wide coverage, line-specific denominator handling across hazards and persisted end-to-end verification remain outstanding. |
| 66 Infrastructure criticality | READY_WITH_LIMITATIONS | Engine emits verified service context and missing-evidence explanations. Numeric score is withheld without calibrated normalization, network topology, served load and redundancy evidence. |
| 67 Service dependencies | READY_WITH_LIMITATIONS | Verified, candidate, and unknown relationships are distinct; proximity never creates a dependency. No verified feeder/service relationship dataset is loaded. |
| 68 Population exposed | READY_WITH_LIMITATIONS | WorldPop 2024 raster is locally validated. Live processing persisted 374 event and administrative exposure rows, including county/ward summaries and quality/coverage evidence. Estimates represent residents in source footprints, not confirmed impacts or people served by energy assets. |
| 69 Vulnerability | READY_WITH_LIMITATIONS | The national run `edabcb94-a39c-4513-91de-851148d07df3` persisted 101,989 per-asset evidence assessments and 1,274 ward plus 47 county summaries; national composite scores remain withheld. A separate teammate-owned Kano/Nyando pilot has 64 persisted screening assessments in the shared database. Pilot scores are explicitly scoped and are not national validated scores. |
| 70 Grid resilience | READY_WITH_LIMITATIONS | The completed run persisted 101,989 per-asset dimension records; redundancy, topology and outage/restoration dimensions remain unassessed, so no composite score is emitted. |
| 71 Confidence/data quality | READY_WITH_LIMITATIONS | Run, source version, quality-check and spatial-coverage records are used by implemented workflows. A universal quality framework across all source families remains outstanding. |
| 72 Intervention scenarios | READY_WITH_LIMITATIONS | The completed run persisted 10,529 deterministic, unranked field-verification candidates for measured asset exposures. Intervention effects and cost-effectiveness remain unavailable. |
| 73 Run/provenance | READY_WITH_LIMITATIONS | Run `edabcb94-a39c-4513-91de-851148d07df3` completed all 101,989 assets, 1,274 ward summaries and 47 county summaries. Acquisition and assessment adapters persist runs and versions. `npm run oseas:pipeline` writes `outputs/last_pipeline_run.json`; a single all-stage run with every optional source configured remains pending. |

## Verified national evidence assessment

The evidence-gated run completed after resuming committed checkpoints across database session drops. Read-only verification found exactly one criticality, dependency, vulnerability and resilience row per asset (101,989 each), 10,529 intervention candidates, 1,274 ward summaries and 47 county summaries, with no duplicate IDs in those run outputs. Energy inventory duplicate source keys are zero. Numeric vulnerability, criticality and resilience scores remain withheld where validated topology, condition, redundancy, served load or outage evidence is absent. The earlier empty run `0998bbd4-d04f-4f28-9446-966a3fe79ac7` is marked failed as superseded and has no assessment rows.

## Shared-database Kano/Nyando pilot integration

The teammate's `evuln` scoring repository remains separate; no code or national inventory rows were merged. The shared PostGIS database contains 64 assets under `source_dataset_key='osm_kano_pilot'`, 192 hazard records (64 flood, 64 heat, 64 wildfire), and 64 vulnerability records. Flood records have 25 `exposed` and 39 `not_exposed` screening outcomes. All 64 heat and 64 wildfire records are `not_assessed`, not zero risk.

The read-only API returns all 64 assets for the pilot bbox and source filter. Kolwa East Substation returns flood exposure `0.6001` for 2011–2020, vulnerability `0.4801` / `moderate`, and the scoring assumptions and source provenance. These are the pilot's screening heuristics; its vulnerability confidence is unknown. API routes expose the pilot result without changing national assessment rules.

## Verified UNOSAT result

The importer completed on 2026-10-14. A read-only database query verified 4 rows and 4 distinct source feature IDs in `flood_reference_features` for `kenya_flood_2024_unosat`. It simplifies only operational geometries at a documented ~5.6 m tolerance; source files/checksums and original feature properties remain available. This does not make the reference field validated.

## 2026-10-15 live pipeline and API check

The live readiness API returned `ready_with_limitations`, `apiReadyForIntegration=true`, a healthy PostGIS connection, and the installed output schema. It reports the latest usable flood run separately from the most recent attempt, so a failed or running retry does not hide already persisted evidence. The API served the bounded Sentinel-1 flood candidate (1 feature) and CHIRPS rainfall layer (7,878 rows). Read-only checks returned 102,179 asset-exposure rows, 101,989 criticality rows, 102,053 vulnerability rows, and 374 population-exposure rows. The service-dependency layer is empty because no verified feeder/service links have been provided; it correctly reports `not_assessed`.

The Nairobi/Kiambu Prithvi run `49910391-e43b-4bf6-8cd9-fadc737ce709` completed in 205 seconds. The 2024-05-02 scene has 99.58% clear AOI pixels after QA60 masking despite 62.9% scene-wide cloud cover. The class raster contains 4,504 water/flood candidate pixels and polygonizes to 3 components, persisted as one unioned MultiPolygon event. Zero energy assets lie in this small AOI; four county/ward summaries are partial. The result is inference-only and not independently validated for Kenya.

## WorldPop processing contract

The processor counts valid raster cell centers in each flood footprint and intersecting county/ward geometry. Overlapping source polygons are unioned in raster space so a cell contributes at most once per event. A geometry outside the raster or containing no pixel centers is represented as no coverage, not as a measured zero. Population values are modeled estimates; uncertainty and valid-cell fraction are retained.

## Supported single command

```powershell
npm run oseas:pipeline
```

The command performs schema preflight, configured vector source ingestion, administrative assignment, NASA POWER heat retrieval, Black Marble when the complete 36-month period is configured, UNOSAT import, CHIRPS event rainfall summaries, WorldPop acquisition and persistence, evidence-gated assessments, FIRMS when configured, and bounded Sentinel-1/Prithvi flood stages when their AOI and dates are supplied. The checked-in pilot config uses a 45-day pre-event baseline and a 4.92 km2 Prithvi AOI; `OSEAS_PRITHVI_MAX_CLOUD_PERCENT` controls scene-wide filtering while the adapter enforces AOI-local clear-pixel coverage. Black Marble does not require a NASA LAADS token. Optional or unsupported sources are reported as blocked/limited rather than represented as successful empty outputs.

## Remaining source and validation work

- Broader ERA5 rainfall products, threshold-based extreme-rainfall indicators, and Kenya-specific validation remain outstanding; the CHIRPS event-window adapter has completed its first live run.
- Reusable DEM-derived terrain and drainage products beyond flood-screen slope filtering.
- Landsat LST quality-masked composites and comparison with NASA POWER air-temperature context.
- NASA MODIS/Copernicus burned-area acquisition and exposure (FIRMS points are not perimeters).
- Kenya-specific validation with compatible reference labels and precision/recall/IoU; no validation metrics are available.
- Asset-to-administrative assignment refresh completed with 101,939 of 101,989 assets assigned (193,390 ward/county rows); 50 assets lack a county/ward assignment.
- FIRMS latest-day acquisition is configured; the 2026-10-14 run returned zero detections and partial coverage, not a no-fire conclusion. Black Marble uses the same Earth Engine credentials as the imagery pipeline and the explicit full-month interval in `.env`.
- The single-command runner now has explicit bounded flood dates, a baseline within the processor's 45-day limit, CHIRPS and Prithvi cloud-filter settings. A fresh all-stage orchestration has not been completed in one invocation; persisted stages have been verified individually. The national night-lights batch is not running: its local log/checkpoints are incomplete, and no database run record exists. Unsupported sources and missing scientific validation remain reported as limitations.
