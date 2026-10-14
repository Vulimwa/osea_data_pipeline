# OSEAS backend implementation status

Assessment date: 2026-10-14. This report distinguishes code in the repository from results actually acquired or persisted. `READY` means executable and evidenced; `READY_WITH_LIMITATIONS` means a working bounded workflow with known gaps; `BLOCKED` means execution depends on a stated external input or the active import; `NOT_IMPLEMENTED` means no complete processing chain exists.

| Deliverable | Status | What exists and what is still missing |
|---|---|---|
| 59 Standardized energy inventory | READY_WITH_LIMITATIONS | Earth Engine ingestion, normalization, deterministic source keys, PostGIS upserts and admin assignment exist. The historic run recorded 323 rejected geometries across four source assets; configured source coverage is not proof of national completeness. |
| 60 Flood extent | READY_WITH_LIMITATIONS | Distinct Sentinel-1 baseline, Sentinel-2 Prithvi workflow, and UNOSAT reference ingestion are implemented. The user-started UNOSAT run is currently marked `running`; latest local check showed zero imported rows and no end timestamp. No compatible scientific validation metrics are available. |
| 61 Rainfall indicators | NOT_IMPLEMENTED | CHIRPS/ERA5 catalog entries and rainfall context in flood screening exist. There is no persisted accumulation/anomaly/extreme-rainfall product workflow. |
| 62 Terrain/drainage | READY_WITH_LIMITATIONS | DEM slope is used by the Sentinel-1 flood screen; no reusable national terrain, flow accumulation or asset-level drainage output has been executed and persisted. |
| 63 Heat exposure | NOT_IMPLEMENTED | Landsat/ERA5 sources are cataloged; no quality-masked LST/air-temperature assessment output is produced. |
| 64 Wildfire | NOT_IMPLEMENTED | FIRMS and MODIS sources are cataloged; no fire acquisition/exposure processor is implemented. |
| 65 Asset hazard exposure | READY_WITH_LIMITATIONS | Flood candidate polygons can be intersected with inventory assets and summaries. This does not yet cover every hazard, full geometry-specific denominators, or all source products. |
| 66 Infrastructure criticality | NOT_IMPLEMENTED | Tables and map layer contract exist. No defensible score is calculated; current response must be interpreted as unassessed. |
| 67 Service dependencies | READY_WITH_LIMITATIONS | Relationship tables and map layer exist. No verified feeder/service relationship source is loaded; proximity is not treated as dependency. |
| 68 Population exposed | READY_WITH_LIMITATIONS | WorldPop 2024 Global2 download, cell-center zonal processor, local preview, idempotent persistence, county/ward intersections, coverage records and a filtered map endpoint are implemented. Current download/preview has not yet been verified complete; no population result has been persisted. Results estimate residents inside a reference flood footprint, not confirmed impacted people or people served by assets. |
| 69 Vulnerability | NOT_IMPLEMENTED | Output schema/API exist; no evidence-supported scoring method is executed. |
| 70 Grid resilience | NOT_IMPLEMENTED | Schema/API exist; operational redundancy, outage and topology evidence are not available for a defensible composite score. |
| 71 Confidence/data quality | READY_WITH_LIMITATIONS | Run provenance, data-quality checks and spatial coverage schemas/process records exist for implemented workflows. There is no complete shared quality framework across all source families. |
| 72 Intervention scenarios | NOT_IMPLEMENTED | Scenario storage and read APIs exist. No deterministic baseline-versus-intervention engine or ranking is calculated. |
| 73 Run/provenance | READY_WITH_LIMITATIONS | Ingestion/model run tables, quality checks, versions and API routes exist. Current run completeness varies by pipeline; the in-progress import has not recorded completion or progress rows. |

## WorldPop processing contract

The source adapter fetches the Kenya annual constrained population-count GeoTIFF for a selected year (default 2024). The processor unions overlapping input flood polygons by event, counts each raster cell once per event when the cell center falls inside the footprint, and estimates zonal counts for the full event plus intersecting county/ward polygons already present in `administrative_units`. A per-zone valid-raster fraction distinguishes missing raster coverage from a measured zero. It does not double-count overlapping polygons within an event.

The current WorldPop R2025A v1 product is an alpha modeled population surface, in estimated persons per pixel. The method does not establish that residents were affected, displaced, or dependent on any specific energy asset. Independent event-specific validation is not yet available. See [WorldPop's product listing](https://hub.worldpop.org/geodata/listing?id=135) and [product catalog](https://hub.worldpop.org/project/categories?id=3).

Commands:

```powershell
npm run oseas:population:audit
npm run oseas:population:download
npm run oseas:population:exposure
npm run oseas:population:persist
```

The local exposure command writes `outputs/worldpop_unosat_2024.geojson` and a JSON manifest without database writes. Persistence requires prior UNOSAT reference rows, county/ward geometries, the additive schema, and no active UNOSAT reference run. The persistence command checks this before writing.

## Current operational blocker

The original Windows Python process PID 2540 still appears in the process table with command line `python scripts/ingest_unosat_flood_reference.py`, but it has no active PostgreSQL session or advisory lock. Run `94d46fda-53b3-4ad2-9ed3-03114c4fd831` was safely marked `failed` by stale-run recovery after acquiring the importer locks; no feature rows were changed. The database has zero UNOSAT rows. Because that old process remains present, the population `--persist` command detects it and refuses to write. Do not launch a replacement import until PID 2540 exits; then verify the run and feature counts. The importer has since been changed to stream and commit small batches, so a later rerun records partial progress and is idempotent.
