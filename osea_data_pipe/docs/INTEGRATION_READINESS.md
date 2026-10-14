# OSEAS integration readiness

Assessment date: 2026-10-14. This page separates code present in the repository from work verified against live Earth Engine and PostGIS services.

## Current state

| Area | State | Evidence / remaining work |
|---|---|---|
| Infrastructure inventory ingestion | Completed with geometry warnings | Run `28645a80-fc57-4d32-bffe-b2e21d941e2d` read all 14 configured assets. Zero entire assets failed; 4 assets had 323 source features skipped for unusable geometry. The warnings and feature counts are persisted. |
| Duplicate prevention | Verified after ingestion | Deterministic source identifiers, upserts, and unique source constraints are active. `npm run oseas:status` reports zero duplicate source keys. |
| Database schema | Ready; verified 2026-10-14 | `npm run db:setup` connected to PostGIS 3.3 and verified the core plus assessment/output tables. This is a read-only check. No database reset or drop was run. |
| Historic energy/service Earth Engine ingestion | Completed with geometry warnings | The saved historic run read 14 infrastructure/service/boundary assets. Individual empty/missing geometries were skipped; source pages completed and deterministic upserts prevent duplicates. |
| Climate/satellite source availability | Read-only smoke audit passed for selected Earth Engine collections | CHIRPS (30), ERA5-Land (30), ERA5 daily (30, April 2019), Sentinel-1 (4), Sentinel-2 SR/L1C (6 each), Landsat 8 L2 (2), Copernicus DEM, JRC surface water and MODIS burned area (12) returned data over Nairobi. This verifies availability only; rasters were not downloaded or persisted. |
| Sentinel-1 flood screen | Implemented baseline; not run or scientifically validated | Small-area, same-orbit relative-backscatter candidate screen with DEM slope and permanent-water masks, CHIRPS rainfall context, scene provenance, PostGIS polygons, asset intersections and ward/county summaries. Requires completed inventory ingestion, applied schema, EE access, suitable event/reference dates, and >=70% scene footprint coverage. Output is explicitly modeled candidate evidence. |
| Other listed datasets | Mixed: implemented and registered adapters; several remain unavailable | The catalog shows which sources have retrieval adapters, which only have catalog entries, and which have blocked product/credential selection. Registration is not ingestion. See [`DATA_CATALOG.md`](DATA_CATALOG.md). |
| Prithvi | Real Kenya inference and geospatial persistence completed; scientific validation not evaluated | Run `6860135c-5c64-4b9a-bfdb-b9f30a505b93` processed Sentinel-2 L1C scene `20240429T072621_20240429T074427_T37MEV` over a 1.48 km² Garissa pilot AOI. It produced five candidate polygons, zero asset intersections among 11 AOI assets, and four partial county/ward summaries. Output geometry passed PostGIS validity checks. No independent pixel reference was used; see [`PRITHVI_KENYA_VALIDATION.md`](PRITHVI_KENYA_VALIDATION.md). |
| WorldPop population | Acquisition ready; local processing running; persistence blocked | WorldPop Global2 R2025A v1, year 2024, was downloaded and validated locally (9,596 × 11,726, EPSG:4326, SHA256 recorded). The cell-center zonal processor and idempotent county/ward persistence are implemented. Local processing is running; no result rows have been persisted. Persistence refuses to run while the legacy UNOSAT Python PID 2540 remains present. |
| OSEAS API | Implemented; schema verified | Read-only routes expose readiness, catalog, runs, candidate/reference floods, hydrography, GeoTIFF resources, and stored derived-output GeoJSON. Production routes validate Supabase access tokens. |
| Frontend | Deferred | No frontend integration was undertaken; the OSEAS API is the current pipeline boundary. |

## Dataset coverage

The three supplied Kenya Earth Engine layers passed a live asset audit: rivers (13,914 features), lakes (46 features with mixed Polygon/GeometryCollection types), and Nov 2023 flood reference (39 polygon features). Ingestion support, source-key upserts, provenance columns and GeoJSON routes are implemented. The current database schema is installed; source rows are available only where the targeted import has completed. Lake polygons can be used as a permanent-water exclusion in the Sentinel-1 baseline; river geometry remains context. The event-level area/population supplied for ADAM `FL-20231121-KEN-03` are stored as reported metadata, distinct from measured source-feature areas.

The three Global Wind Atlas country GeoTIFF endpoints returned HTTP 200 with TIFF content and have now been downloaded and inspected locally: each is 4,287 x 3,829 cells at 0.0025 degree spacing, WGS 84 geographic coordinates, and covers the Kenya bounding envelope. The inspected Kenya-envelope valid sample fractions are 70.3%; map copies mask negative values to nodata and retain source rasters/checksums. `wind_speed_10m` samples range 0.0441–17.2 m/s, `power_density_10m` 0.0000021–8,070 W/m2, and `air_density_10m` 0.728–1.17 kg/m3. These are sample ranges, not national summaries. The separate country GeoJSON URL returned HTTP 400. Wind layers are resource context, never a hazard or asset-failure score. See [`DATA_CATALOG.md`](DATA_CATALOG.md) and [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md).

The `/layers/{output}/geojson` routes expose stored climate, terrain, land cover, fire, exposure, vulnerability, criticality, service dependency, administrative summary, intervention, population exposure, grid resilience and coverage records. The WorldPop processor is implemented and its raster is locally validated, but no population results have been persisted yet. Other empty outputs remain `not_assessed`.

All requested source families are recorded in the canonical [`data_catalog.json`](../config/data_catalog.json): CHIRPS, ERA5, NASA POWER, WorldClim, future projections, DEM, Sentinel-1, Sentinel-2, Landsat temperature, land cover, HydroSHEDS/OSM, event flood references, EM-DAT/ReliefWeb, FIRMS and MODIS burned area. Current processing implementations are narrower: the infrastructure ingest reads configured OSEAS vector assets; the flood baseline uses Sentinel-1, DEM and permanent-water masking plus CHIRPS context. The other products need source-specific adapters, product selections, unit checks, provenance and appropriate validation before their outputs can be treated as operational.

Derived output schema covers hazard events, flood extents, terrain and land-cover metrics, exposures, vulnerability/criticality/dependency records, administrative summaries, interventions and provenance. A table existing does not mean a corresponding assessment has been calculated. Unsupported outputs remain `not_assessed`/unavailable rather than fabricated.

## Required acceptance sequence

1. The additive [`../database/schema.sql`](../database/schema.sql) is applied in the current Supabase database. Re-run `npm run db:setup` after future schema changes.
2. The latest inventory run is complete with four geometry-warning datasets and zero failed assets. Check `npm run oseas:status`; duplicate source keys are currently zero.
3. Asset-to-admin assignment refresh is available as `npm run oseas:assign-admin`; the Prithvi pilot computes AOI-local ward/county summaries directly and does not run a national assignment refresh.
5. For a selected event only, run the bounded flood screen with a documented reference window and AOI; independently compare candidates to available reference flood data before using them for planning.
6. Inspect `/api/v1/oseas/readiness`, run provenance, quality checks, geometry and summaries. Treat results as screening evidence until validated.

Use the commands and constraints in [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md). The repository can be locally tested without starting ingestion, but live end-to-end acceptance requires the user's credentials, schema application and later operator run.
