# OSEAS backend implementation status

Assessment date: 2026-10-14. Status reflects code and observed results; configured sources and runnable processors are not represented as persisted data.

| Deliverable | Status | Evidence and remaining limitation |
|---|---|---|
| 59 Standardized energy inventory | READY_WITH_LIMITATIONS | Earth Engine ingestion, normalization, deterministic source keys, PostGIS upserts and county/ward assignment exist. Historic run recorded rejected geometries; configured data is not proof of national completeness. |
| 60 Flood extent | READY_WITH_LIMITATIONS | Sentinel-1 and Sentinel-2 Prithvi candidate workflows exist. UNOSAT run `f7ca7842-711f-4840-8037-04abc337448e` completed and upserted 4 unique reference polygons. Source field validation remains incomplete; no flood model scientific metrics are claimed. |
| 61 Rainfall indicators | IMPLEMENTED_PENDING_LIVE_RUN | `scripts/ingest_chirps_rainfall.py` calculates event-window 30-day CHIRPS totals, absolute anomalies and percentage anomalies by county/ward, with deterministic upserts, quality checks, versions and provenance. It requires persisted dated reference events and has not yet run against the current database; extreme-rainfall thresholds and independent Kenya validation remain outstanding. Query `/api/v1/oseas/layers/rainfall/geojson`. |
| 62 Terrain/drainage | READY_WITH_LIMITATIONS | DEM slope is used by Sentinel-1 screening. A reusable terrain/drainage product, flow accumulation and asset association have not been executed. |
| 63 Heat exposure | READY_WITH_LIMITATIONS | NASA POWER daily T2M_MAX, provider monthly-climatology anomalies, hot-day screens, grid-cell events, source versions and nearest-cell asset screening completed for 2024. Live run `e65d4f92-39a4-4b7e-aae3-49c7cbd05440` has 215,208 daily/climatology observations, 294 grid cells, 101,987 asset exposure rows and 1,261 ward/county summaries. Coarse (~0.5-degree) air temperature is not Landsat LST; this is hazard exposure context, not asset damage or outage evidence. |
| First-class night-lights context | READY_WITH_LIMITATIONS | NASA VIIRS Black Marble VNP46A2 daily imagery is read through the authenticated Earth Engine catalog, quality-screened, composited by month, and stored as county, ward, asset and service summaries with stable API map rows. The national run uses 2023-08 through 2026-07 against a 2012-01 through 2015-12 baseline; January 2012 is partial. Live row counts and run ID are added after the current ingestion completes. |
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

## WorldPop processing contract

The processor counts valid raster cell centers in each flood footprint and intersecting county/ward geometry. Overlapping source polygons are unioned in raster space so a cell contributes at most once per event. A geometry outside the raster or containing no pixel centers is represented as no coverage, not as a measured zero. Population values are modeled estimates; uncertainty and valid-cell fraction are retained.

## Supported single command

```powershell
npm run oseas:pipeline
```

The command performs schema preflight, configured vector source ingestion, administrative assignment, NASA POWER heat retrieval, Black Marble when Earth Engine is authenticated and the complete 36-month period is configured, UNOSAT import, WorldPop acquisition and persistence, evidence-gated assessments, and FIRMS when configured. Black Marble does not require a NASA LAADS token. Flood event screening requires an explicitly bounded AOI and periods. Optional or unsupported sources are reported as blocked/limited rather than represented as successful empty outputs.

## Remaining source and validation work

- CHIRPS event-window rainfall adapter is implemented but needs its first live run; broader ERA5 rainfall products, threshold-based extreme-rainfall indicators, and Kenya-specific validation remain outstanding.
- Reusable DEM-derived terrain and drainage products beyond flood-screen slope filtering.
- Landsat LST quality-masked composites and comparison with NASA POWER air-temperature context.
- NASA MODIS/Copernicus burned-area acquisition and exposure (FIRMS points are not perimeters).
- Kenya-specific validation with compatible reference labels and precision/recall/IoU; no validation metrics are available.
- Asset-to-administrative assignment refresh completed with 101,939 of 101,989 assets assigned (193,390 ward/county rows); 50 assets lack a county/ward assignment.
- FIRMS latest-day acquisition is configured; the 2026-10-14 run returned zero detections and partial coverage, not a no-fire conclusion. Black Marble uses the same Earth Engine credentials as the imagery pipeline and the explicit full-month interval in `.env`.
- A complete single-command run remains pending because the bounded Sentinel-1 screen needs an explicitly selected AOI plus event and baseline dates; unsupported products and unavailable validation evidence are reported as limitations. Automated Python, Node, lint and build checks pass.
