# OSEAS backend implementation status

Assessment date: 2026-10-14. Status reflects code and observed results; configured sources and runnable processors are not represented as persisted data.

| Deliverable | Status | Evidence and remaining limitation |
|---|---|---|
| 59 Standardized energy inventory | READY_WITH_LIMITATIONS | Earth Engine ingestion, normalization, deterministic source keys, PostGIS upserts and county/ward assignment exist. Historic run recorded rejected geometries; configured data is not proof of national completeness. |
| 60 Flood extent | READY_WITH_LIMITATIONS | Sentinel-1 and Sentinel-2 Prithvi candidate workflows exist. UNOSAT run `f7ca7842-711f-4840-8037-04abc337448e` completed and upserted 4 unique reference polygons. Source field validation remains incomplete; no flood model scientific metrics are claimed. |
| 61 Rainfall indicators | NOT_IMPLEMENTED | CHIRPS/ERA5 are registered and used as context in flood screening. Persisted rainfall accumulations, anomalies and extreme-rainfall indicators are still outstanding. |
| 62 Terrain/drainage | READY_WITH_LIMITATIONS | DEM slope is used by Sentinel-1 screening. A reusable terrain/drainage product, flow accumulation and asset association have not been executed. |
| 63 Heat exposure | READY_WITH_LIMITATIONS | NASA POWER daily T2M_MAX, provider monthly-climatology anomalies, configurable hot-day screens, grid-cell events, source versions and nearest-grid asset screening are implemented. Coarse (~0.5-degree) near-surface air temperature is not Landsat LST. Live persistence is pending verification. |
| 64 Wildfire | BLOCKED | NASA FIRMS adapter stores active-fire points, source confidence category, proximity evidence and coverage. Requires `NASA_FIRMS_MAP_KEY` and explicit dates. It does not produce perimeters, burned area or damage claims. |
| 65 Asset hazard exposure | READY_WITH_LIMITATIONS | Existing flood exposure and new heat/fire proximity routines persist asset-linked measurements. Complete source-wide coverage, line-specific denominator handling across hazards and persisted end-to-end verification remain outstanding. |
| 66 Infrastructure criticality | READY_WITH_LIMITATIONS | Engine emits verified service context and missing-evidence explanations. Numeric score is withheld without calibrated normalization, network topology, served load and redundancy evidence. |
| 67 Service dependencies | READY_WITH_LIMITATIONS | Verified, candidate, and unknown relationships are distinct; proximity never creates a dependency. No verified feeder/service relationship dataset is loaded. |
| 68 Population exposed | READY_WITH_LIMITATIONS | WorldPop 2024 raster is locally validated. County/ward exposure processing is rerunning after a zero-height raster-window fix; database persistence and output counts are pending. Estimates represent residents in source footprints, not confirmed impacts or people served by energy assets. |
| 69 Vulnerability | READY_WITH_LIMITATIONS | Per-asset observed exposure context and missing-evidence explanations are persisted; comprehensive score is withheld until sensitivity and adaptive-capacity evidence are present. |
| 70 Grid resilience | READY_WITH_LIMITATIONS | Per-dimension evidence status is persisted; redundancy, topology and outage/restoration dimensions remain unassessed, so no composite score is emitted. |
| 71 Confidence/data quality | READY_WITH_LIMITATIONS | Run, source version, quality-check and spatial-coverage records are used by implemented workflows. A universal quality framework across all source families remains outstanding. |
| 72 Intervention scenarios | READY_WITH_LIMITATIONS | Deterministic unranked field-verification candidates are generated only for measured asset exposure. Intervention effects and cost-effectiveness remain unavailable. |
| 73 Run/provenance | READY_WITH_LIMITATIONS | New acquisition and assessment adapters persist processing runs and versions. `npm run oseas:pipeline` runs supported stages in dependency order and writes `outputs/last_pipeline_run.json`; end-to-end live run remains pending. |

## Verified UNOSAT result

The importer completed on 2026-10-14. A read-only database query verified 4 rows and 4 distinct source feature IDs in `flood_reference_features` for `kenya_flood_2024_unosat`. It simplifies only operational geometries at a documented ~5.6 m tolerance; source files/checksums and original feature properties remain available. This does not make the reference field validated.

## WorldPop processing contract

The processor counts valid raster cell centers in each flood footprint and intersecting county/ward geometry. Overlapping source polygons are unioned in raster space so a cell contributes at most once per event. A geometry outside the raster or containing no pixel centers is represented as no coverage, not as a measured zero. Population values are modeled estimates; uncertainty and valid-cell fraction are retained.

## Supported single command

```powershell
npm run oseas:pipeline
```

The command performs schema preflight, configured vector source ingestion, administrative assignment, NASA POWER heat retrieval, UNOSAT import, WorldPop acquisition and persistence, evidence-gated assessments, and FIRMS when configured. Flood event screening requires an explicitly bounded AOI and periods. Optional or unsupported sources are reported as blocked/limited rather than represented as successful empty outputs.

## Remaining source and validation work

- CHIRPS/ERA5 standalone rainfall anomaly and extreme-rainfall products.
- Reusable DEM-derived terrain and drainage products beyond flood-screen slope filtering.
- Landsat LST quality-masked composites and comparison with NASA POWER air-temperature context.
- NASA MODIS/Copernicus burned-area acquisition and exposure (FIRMS points are not perimeters).
- Kenya-specific validation with compatible reference labels and precision/recall/IoU; no validation metrics are available.
- Verify current heat and WorldPop outputs from the live database; FIRMS needs the private MAP_KEY and requested date window.
- Run and inspect the full configured pipeline and the complete automated test suites after these changes.
