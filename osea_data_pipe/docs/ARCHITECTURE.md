# OSEAS backend architecture

## Implemented flow

The source inventory also includes Kenya rivers/lakes and the separate Nov 2023 reference flood layer. Those sources have dedicated PostGIS tables and GeoJSON endpoints. Sentinel-1 and Prithvi supplement JRC permanent-water handling with mapped lake polygons when the lake asset is configured; rivers remain context to avoid masking actual floodplain inundation.

```text
Configured Earth Engine feature assets
  -> paged, batched, idempotent source ingestion (oseas.ingest)
  -> PostGIS energy assets, services, administrative boundaries, run/version/quality records
  -> boundary assignment (point covered-by; line/polygon intersection measures)
  -> explicit bounded event-window flood screen
       Sentinel-1 VV event median vs same-orbit baseline median
       + slope and JRC persistent-water masks
       + CHIRPS rainfall context
  -> modeled candidate polygons and positive asset intersections in PostGIS
  -> ward/county screening counts with explicit method and run provenance
  -> read-only Express endpoints and GeoJSON
```

Raster work runs in Earth Engine. The backend only retrieves bounded vector candidates (maximum 1,000 km² and 500 polygons per run) and writes those plus asset intersections to PostGIS. It does not download full raster collections into application memory. Larger national analysis needs a tile/export and object-storage design before operation.

## Ingestion and idempotency

The importer pages Earth Engine tables and writes one bounded transaction per page. Stable IDs derive from the source dataset and source feature ID, with deterministic serialized-feature fallback. Database unique constraints on `(source_dataset_key, source_feature_id)` and upserts make reruns reconcile committed features. A PostgreSQL session advisory lock prevents concurrent importers. It does not delete source rows.

## Flood method and evidence

The current baseline is `oseas-s1-relative-backscatter-screen-v2`. It requires explicit non-overlapping event and baseline windows, an EPSG:4326 bounding box no larger than 1,000 km², and a same-orbit Sentinel-1 VV stack with at least 70% footprint coverage in both windows. It applies VV and change thresholds, a terrain-slope filter, JRC and optional mapped-lake permanent-water masks, a connected-pixel filter and a minimum patch area.

Results are `modeled` candidate polygons, not confirmed inundation. CHIRPS event-window rainfall is stored as context and does not drive the classifier. No candidate intersection is converted into a zero risk score. Asset exposure rows are written only for positive geometry intersections. Administrative summaries leave exposure fractions null because satellite coverage and asset completeness may be incomplete. The method has not been validated against independent Kenya flood reference polygons.

## Dataset registry

`config/data_catalog.json` is the shared registry for Earth Engine collections, direct APIs, public downloads and event-specific references. The bounded flood workflow currently uses Sentinel-1, CHIRPS, Copernicus DEM and JRC Global Surface Water. Other listed climate, optical, thermal, land-cover, fire and event sources remain registered with explicit retrieval states; they are not represented as ingested unless a successful run is stored.

## API

The existing Express service mounts OSEAS read-only routes at `/api/v1/oseas`. Its responses use EPSG:4326 GeoJSON for map features and explicit `not_assessed` states when outputs are absent. `/api/v1/oseas/readiness` is authoritative; the root health endpoint is a liveness/database check, not scientific readiness.

## Boundaries and retired starter code

Administrative point assets are assigned using `ST_Covers`. Lines and polygons are assigned using intersections; lengths and areas are measured on the clipped geometry in geography units. Current assignments are refreshable and marked through `is_current`.

The old Kilimani AOI, generated development-change labels, Kili detection routes and case-management routes have been removed from the active backend. Only shared Earth Engine authentication and PostgreSQL/API infrastructure remain reused. The OSEAS frontend is unchanged.
