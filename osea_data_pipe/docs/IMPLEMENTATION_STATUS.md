# OSEAS backend implementation status

Assessment date: 2026-10-14. Status reflects code and observed results; configured sources and runnable processors are not represented as persisted data.

| Deliverable | Status | Evidence and remaining limitation |
|---|---|---|
| 59 Standardized energy inventory | READY_WITH_LIMITATIONS | Earth Engine ingestion, normalization, deterministic source keys, PostGIS upserts and county/ward assignment exist. Historic run recorded rejected geometries; configured data is not proof of national completeness. |
| 60 Flood extent | READY_WITH_LIMITATIONS | Sentinel-1 and Sentinel-2 Prithvi candidate workflows exist. UNOSAT run `f7ca7842-711f-4840-8037-04abc337448e` completed and upserted 4 unique reference polygons. Source field validation remains incomplete; no flood model scientific metrics are claimed. |
| 61 Rainfall indicators | NOT_IMPLEMENTED | CHIRPS/ERA5 are registered and used as context in flood screening. Persisted rainfall accumulations, anomalies and extreme-rainfall indicators are still outstanding. |
| 62 Terrain/drainage | READY_WITH_LIMITATIONS | DEM slope is used by Sentinel-1 screening. A reusable terrain/drainage product, flow accumulation and asset association have not been executed. |
| 63 Heat exposure | READY_WITH_LIMITATIONS | NASA POWER daily T2M_MAX, provider monthly-climatology anomalies, hot-day screens, grid-cell events, source versions and nearest-cell asset screening completed for 2024. Live run `e65d4f92-39a4-4b7e-aae3-49c7cbd05440` has 215,208 daily/climatology observations, 294 grid cells, 101,987 asset exposure rows and 1,261 ward/county summaries. Coarse (~0.5-degree) air temperature is not Landsat LST; this is hazard exposure context, not asset damage or outage evidence. |
| First-class night-lights context | READY_WITH_LIMITATIONS | NASA VIIRS Black Marble VNP46A3 is in the catalog with a monthly quality-masked adapter, manifest-checked exactly-36-month input contract, fixed 2012-2015 baseline, 500 m asset/service context buffers, stable map rows, API layer and readiness status. No live radiance output is claimed because `NASA_EARTHDATA_TOKEN` and manifest-selected recent dates are not configured. |
| 64 Wildfire | BLOCKED | NASA FIRMS adapter stores active-fire points, source confidence category, proximity evidence and coverage. Requires `NASA_FIRMS_MAP_KEY` and explicit dates. It does not produce perimeters, burned area or damage claims. |
| 65 Asset hazard exposure | READY_WITH_LIMITATIONS | Existing flood exposure and new heat/fire proximity routines persist asset-linked measurements. Complete source-wide coverage, line-specific denominator handling across hazards and persisted end-to-end verification remain outstanding. |
| 66 Infrastructure criticality | READY_WITH_LIMITATIONS | Engine emits verified service context and missing-evidence explanations. Numeric score is withheld without calibrated normalization, network topology, served load and redundancy evidence. |
| 67 Service dependencies | READY_WITH_LIMITATIONS | Verified, candidate, and unknown relationships are distinct; proximity never creates a dependency. No verified feeder/service relationship dataset is loaded. |
| 68 Population exposed | READY_WITH_LIMITATIONS | WorldPop 2024 raster is locally validated. Live processing persisted 374 event and administrative exposure rows, including county/ward summaries and quality/coverage evidence. Estimates represent residents in source footprints, not confirmed impacts or people served by energy assets. |
| 69 Vulnerability | READY_WITH_LIMITATIONS | Per-asset observed exposure context, missing-evidence explanations and current ward/county map summaries are persisted. Admin summaries include assigned asset denominators, asset-type and system-class counts (central network, mini-grid, distribution, generation and unknown), and hazard-specific exposure counts. Composite vulnerability score remains withheld until sensitivity, adaptive capacity, topology and calibrated validation evidence exist. |
| 70 Grid resilience | READY_WITH_LIMITATIONS | Per-dimension evidence status is persisted; redundancy, topology and outage/restoration dimensions remain unassessed, so no composite score is emitted. |
| 71 Confidence/data quality | READY_WITH_LIMITATIONS | Run, source version, quality-check and spatial-coverage records are used by implemented workflows. A universal quality framework across all source families remains outstanding. |
| 72 Intervention scenarios | READY_WITH_LIMITATIONS | Deterministic unranked field-verification candidates are generated only for measured asset exposure. Intervention effects and cost-effectiveness remain unavailable. |
| 73 Run/provenance | READY_WITH_LIMITATIONS | Acquisition and assessment adapters persist processing runs and versions. `npm run oseas:pipeline` runs configured stages in dependency order and writes `outputs/last_pipeline_run.json`; supported component runs were verified individually, while a single all-stage run with every optional source configured remains pending. |

## Verified UNOSAT result

The importer completed on 2026-10-14. A read-only database query verified 4 rows and 4 distinct source feature IDs in `flood_reference_features` for `kenya_flood_2024_unosat`. It simplifies only operational geometries at a documented ~5.6 m tolerance; source files/checksums and original feature properties remain available. This does not make the reference field validated.

## WorldPop processing contract

The processor counts valid raster cell centers in each flood footprint and intersecting county/ward geometry. Overlapping source polygons are unioned in raster space so a cell contributes at most once per event. A geometry outside the raster or containing no pixel centers is represented as no coverage, not as a measured zero. Population values are modeled estimates; uncertainty and valid-cell fraction are retained.

## Supported single command

```powershell
npm run oseas:pipeline
```

The command performs schema preflight, configured vector source ingestion, administrative assignment, NASA POWER heat retrieval, Black Marble when its token and complete 36-month period are configured, UNOSAT import, WorldPop acquisition and persistence, evidence-gated assessments, and FIRMS when configured. Flood event screening requires an explicitly bounded AOI and periods. Optional or unsupported sources are reported as blocked/limited rather than represented as successful empty outputs.

## Remaining source and validation work

- CHIRPS/ERA5 standalone rainfall anomaly and extreme-rainfall products.
- Reusable DEM-derived terrain and drainage products beyond flood-screen slope filtering.
- Landsat LST quality-masked composites and comparison with NASA POWER air-temperature context.
- NASA MODIS/Copernicus burned-area acquisition and exposure (FIRMS points are not perimeters).
- Kenya-specific validation with compatible reference labels and precision/recall/IoU; no validation metrics are available.
- Complete the active evidence assessment run and verify its persisted asset, ward and county outputs. Current asset-to-administrative assignment refresh completed with 101,939 of 101,989 assets assigned (193,390 ward/county rows).
- FIRMS needs the private MAP_KEY and requested date window; Black Marble needs a NASA Earthdata token and recent dates confirmed against the LAADS manifest.
- CHIRPS/ERA5 standalone rainfall anomaly products, Landsat LST, reusable drainage metrics, drought indicators, burned-area perimeters, validated service topology and outage/restoration evidence remain outstanding. Kenya-specific Prithvi validation still needs compatible reference labels and metrics.
- A complete all-stage pipeline run remains pending because optional data credentials/date windows are not configured; automated Python, Node, lint and build checks passed during this implementation.
