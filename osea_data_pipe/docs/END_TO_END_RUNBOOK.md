# OSEAS end-to-end runbook

## 1. Configure and apply schema

From the backend project directory:

```powershell
npm ci
python -m pip install -r requirements.txt
```

Set `.env` locally with `DB_URL` (or supported PostgreSQL URL alias), `GEE_PROJECT_ID`, Earth Engine credentials, and all supplied `GEE_ASSET_*` values. Do not copy secrets into source control or reports. A FIRMS key is optional until its adapter is implemented.

Paste [`../database/schema.sql`](../database/schema.sql) into Supabase SQL Editor and execute it. It uses additive `CREATE ... IF NOT EXISTS`/`ALTER ... IF NOT EXISTS` statements and does not drop existing data. Then run the read-only schema check:

```powershell
npm run db:setup
```

The bundled 2024 UNOSAT reference polygons are local files and do not require Earth Engine. Check them before database ingestion, then import after the schema check:

```powershell
npm run oseas:flood:unosat:audit
npm run oseas:flood:unosat:ingest
```

The audit is read-only. The import upserts four source polygons by dataset/file/feature key into `flood_reference_features`; it is safe to rerun. The source contains two event codes (`FL20240421KEN`, `FL20240426KEN`) and labels its own field validation as not yet complete. PostGIS repairs invalid polygon topology for storage, while the original attributes remain preserved. This does not validate any model output.

## 2. Check Earth Engine source access

The `.env` now includes the supplied river, lake and Nov 2023 flood Earth Engine asset IDs. After applying the additive schema, run only those sources with `npm run oseas:ingest -- --datasets kenya_rivers,kenya_lakes,kenya_flood_2023_reference`. Page upserts are keyed by the original source feature ID and do not duplicate existing rows.

```powershell
npm run oseas:audit
npm run oseas:catalog:audit
```

The first command checks the configured vector infrastructure assets. The second performs bounded reads of selected climate/satellite collections over a small Nairobi bbox for 2024-04-01 through 2024-05-01; it prints counts and band names, not imagery or credentials. Both require active Earth Engine authentication. The fixed source audit dates test availability only; they are not declared flood events.

## 3. Ingest infrastructure once

```powershell
npm run oseas:status
npm run oseas:ingest
```

The importer pages and batches writes, logs counts/percent/elapsed/ETA, uses deterministic source keys and upserts, and holds a single-writer Postgres advisory lock. Monitor from another terminal with `npm run oseas:status`. The command exits `0` when every configured source succeeds, `2` for a partial run, or `1` for setup/all-source failure. Rerun after fixing a partial source; existing source rows update in place. The run history is retained.

If a machine restart leaves a run marked `running`, first confirm no importer is active, then:

```powershell
npm run oseas:recover-stale
npm run oseas:status
```

Recovery takes the importer lock and changes only abandoned run metadata; feature rows are not deleted.

## 4. Assign assets to wards/counties

After the latest source ingestion is `completed` or `partial` with zero failed source assets:

```powershell
npm run oseas:assign-admin
```

Points use polygon coverage. Lines and polygons use intersections; line lengths and polygon areas are measured on the clipped part in each unit. The flood command refreshes these assignments itself before summaries, so this standalone step is optional when only flood results are needed.

## 5. Run a bounded flood screen

Select an actual event window, a non-overlapping reference period from the same season, and an AOI no larger than 1,000 km². Dates use an inclusive start and exclusive end. The example values below are placeholders; replace them with dates supported by your analysis. A date range is not proof that flooding occurred.

```powershell
npm run oseas:flood:screen -- --bbox 36.70 -1.40 37.00 -1.10 `
  --event-start YYYY-MM-DD --event-end YYYY-MM-DD `
  --baseline-start YYYY-MM-DD --baseline-end YYYY-MM-DD `
  --orbit-pass ASCENDING
```

The processor requires >=70% Sentinel-1 footprint coverage for both windows. Default parameters are event VV < -16 dB, VV change < -3 dB, slope < 5 degrees, JRC occurrence < 80%, and candidate patch area >=10,000 m². The method is an unvalidated flood-candidate screen. It stores candidate polygons, positive asset intersections, source/run provenance and ward/county counts. It does not assign vulnerability, reliability, resilience, outage probability, or zero-risk labels. All query/processing state is bounded; no national raster is downloaded into app memory.

If `GEE_ASSET_KENYA_LAKES` is configured, the Sentinel-1 baseline excludes mapped lake pixels and the Prithvi workflow excludes them after inference; the six model input bands remain unchanged. The S1 workflow records scene-footprint coverage separately from valid-pixel coverage. Both outputs remain unvalidated candidates.

Inspect output:

```powershell
npm run oseas:status
```

Then query readiness, catalog, runs, candidate/reference flood, hydrography and `/layers/{output}/geojson` for the registered output keys documented in [`API_CONTRACTS.md`](API_CONTRACTS.md). These routes read stored evidence and do not fabricate missing layers.

## 6. Global Wind Atlas resource cache

The Kenya wind-speed, power-density and air-density GeoTIFF endpoints returned TIFF data and have been downloaded to the local cache. Each raster is 4,287 x 3,829 cells at 0.0025 degree spacing in WGS 84 geographic coordinates and covers the Kenya bounding envelope. The sync command retries up to three times, caps each source at 100 MB, validates sampled pixels and writes checksums. It retains source rasters and creates map copies with negative values masked to nodata. Cached files are reused unless `GWA_FORCE_REFRESH=1`. The API exposes manifest metadata and GeoTIFF downloads. These are renewable-resource layers, not wind hazard evidence. The separate GWA country GeoJSON route returned HTTP 400; existing OSEAS administrative units provide reporting boundaries. GWA documents country GIS downloads and advises against bulk use of the API: [official GIS files page](https://globalwindatlas.info/en/download/gis-files).

## 7. API and service

```powershell
npm run dev
```

`GET /health/live` checks process liveness; `/health/ready` checks database availability; `/api/v1/oseas/readiness` is the OSEAS source/model/output readiness report. A live HTTP process does not imply that the data or hazard assessment is ready.

In production, call OSEAS routes with `Authorization: Bearer <Supabase access token>`. Configure `SUPABASE_URL` and the server-only `SUPABASE_SERVICE_ROLE_KEY`; never put the service-role key in a client app. `OSEAS_REQUIRE_AUTH=true` enables the same verification in development.

## 8. Prithvi and remaining sources

Set up the pinned Sen1Floods11 Sentinel-2 L1C checkpoint. This downloads and verifies the bundle, then runs official sample inference and requires a non-empty prediction raster before setup passes:

```powershell
npm run oseas:prithvi:setup
```

After the additive OSEAS schema is applied and inventory ingestion succeeds, run a small (maximum 5 km²) AOI and an actual event date window:

```powershell
npm run oseas:prithvi:flood -- --bbox <west> <south> <east> <north> `
  --event-start YYYY-MM-DD --event-end YYYY-MM-DD
```

The first Kenya pilot is recorded in [`PRITHVI_KENYA_VALIDATION.md`](PRITHVI_KENYA_VALIDATION.md). It uses a pinned Garissa Sentinel-2 L1C acquisition, stores candidate flood polygons and asset intersections in PostGIS, writes local map-ready GeoJSON/GeoTIFF/PNG products, and persists AOI-local county/ward summaries. The runner logs scene selection and emits an inference heartbeat every 30 seconds; official CPU inference can take several minutes. A run can complete with zero asset intersections; that means no candidate geometry intersected the inventory assets in that AOI, not that assets are safe.

The model is configured for the correct optical task. Its Kenya accuracy is not evaluated; treat output polygons as screening candidates until independently validated. Other catalogued datasets (ERA5, NASA POWER, WorldClim, climate projections, Sentinel-2, Landsat, land cover, HydroSHEDS/OSM, event references, FIRMS and MODIS) have individual access states in [`DATA_CATALOG.md`](DATA_CATALOG.md); do not treat catalog registration as retrieval.

## Troubleshooting

- **No new run in database while process exists:** check Earth Engine authentication and the terminal output. Do not launch another importer while the original process is active. `oseas:status` includes Postgres importer sessions; an OS process without a DB session is not evidence of ingestion progress.
- **EE authentication:** verify project, account permissions, enabled Earth Engine API and service-account file path. Keep service-account keys out of this repository.
- **No S1 images:** choose a window and orbit pass with actual coverage; do not expand the bbox beyond 1,000 km². Inspect the source audit.
- **Coverage below 70%:** choose a smaller AOI or another valid acquisition window; uncovered places remain unassessed.
- **Missing table/column:** apply the current additive schema in Supabase SQL Editor and rerun `npm run db:setup`.
- **Zero candidate polygons:** this is a warning and an empty model output, not proof of zero flood risk. Check the image counts, coverage, thresholds, and an independent reference source.
- **Too many polygons:** divide the AOI into small tiles or use a future batch/export-backed workflow; do not increase memory limits.
