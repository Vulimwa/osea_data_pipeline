# OSEAS API contracts

Base path: `/api/v1/oseas`. Routes are read-only; processing is started through bounded CLI commands in `END_TO_END_RUNBOOK.md`. Errors follow the service envelope `{ "error": { "code", "message", "details", "correlation_id" } }`. GeoJSON coordinates use longitude/latitude in EPSG:4326. Database `NULL` values remain JSON `null`; absent assessments use explicit `not_assessed` or `insufficient_data` states.

## Routes

| Method and path | Query/body | Response |
|---|---|---|
| `GET /readiness` | None | DB/PostGIS connectivity, source-import run, inventory/output table presence, latest flood run, usable-hazard-output state and Prithvi state. `apiReadyForIntegration` is false until the complete OSEAS schema is installed; it does not mean hazards are scientifically validated. |
| `GET /catalog` | None | Machine registry data, access method, coverage, temporal range, units, attribution, evidence kind, retrieval state and last successful persisted retrieval. |
| `GET /runs?limit=100&offset=0` | limit 1–500; offset >=0 | OSEAS ingestion/processing runs with model diagnostics when linked. |
| `GET /runs/{uuid}` | UUID path | One processing run plus quality checks. `404 NOT_FOUND` if absent. |
| `GET /layers` | None | Available stored hazard evidence types, evidence kinds, counts and map endpoint. Empty list means no outputs. |
| `GET /layers/flood_candidate/geojson?bbox=west,south,east,north&limit=100&offset=0` | Optional EPSG:4326 bbox; limit 1–500 | RFC 7946-style `FeatureCollection`, `pagination.total`, processing run, and `spatialReference`. Returns an empty collection with `status=not_assessed` before the first successful flood run. Feature properties include evidence kind, event dates, source, confidence (null for uncalibrated baseline), and method/quality metadata. |
| `GET /assets?type=distribution_transformer&wardId={uuid}&countyId={uuid}&bbox=...&limit=100&offset=0` | Optional type, one admin ID, bbox and pagination | Asset `FeatureCollection`, source identifiers/properties and pagination. Bbox is lon/lat. |
| `GET /assets/{uuid}/exposure` | UUID path | Asset hazard evidence, periods, exposed status, measured intersection, method provenance and processing run. No rows returns `status=not_assessed`; it does not imply no hazard. |
| `GET /assets/{uuid}/vulnerability` | UUID path | Assessments or `status=not_assessed`; this version does not create vulnerability scores. |
| `GET /administrative/{ward\|county}/{uuid}/summary` | Boundary level and UUID | Boundary as a GeoJSON `Feature` with screening counts and provenance; missing assessment returns `assessmentStatus=not_assessed`. |
| `GET /priorities?limit=100&offset=0` | Pagination | Existing reviewed/candidate intervention scenario records; empty list returns `status=not_assessed`. No automatic priority scores are generated. |

| `GET /layers/flood_reference/geojson?eventKey=FL-20231121-KEN-03&bbox=...&limit=100&offset=0` | Optional event key, EPSG:4326 bbox and pagination | Source-preserving reference polygons with original properties, event/run provenance, geometry-measured area, and separately attributed event-level reported area/population. Reference evidence remains separate from model candidates. |
| `GET /layers/hydrography/geojson?type=river\|lake&bbox=...&limit=100&offset=0` | Optional type, bbox and pagination | Mappable rivers/lakes with source identifiers/properties and ingest run. Source GeometryCollections are preserved. |
| `GET /layers/{climate_observations\|climate_projections\|terrain\|land_cover\|fire\|asset_exposure\|asset_vulnerability\|asset_criticality\|service_dependencies\|administrative_summaries\|interventions\|population_exposure\|grid_resilience\|coverage}/geojson?bbox=...&limit=100&offset=0` | Registered layer key; optional EPSG:4326 bbox and pagination | Common map-ready GeoJSON from durable output records. Empty output returns `status=not_assessed`; properties retain method, source, run, coverage and uncertainty fields that exist for that output. |
| `GET /layers/wind_resource` | None | Cache manifest with GeoTIFF URLs, units, CRS, bounds, dimensions, checksums and retrieval metadata; returns `not_cached` plus sync command before download. These layers show resource context, not wind hazards. |
| `GET /layers/wind_resource/{wind_speed_10m\|power_density_10m\|air_density_10m}/geotiff` | Product ID path | Cached GeoTIFF bytes (`image/tiff`) for GeoTIFF-capable map clients. Populate with `npm run oseas:wind:sync`. |

## Examples

```http
GET /api/v1/oseas/readiness
GET /api/v1/oseas/assets?type=primary_substation&bbox=36.7,-1.4,37.0,-1.1&limit=50
GET /api/v1/oseas/layers/flood_candidate/geojson?bbox=36.7,-1.4,37.0,-1.1
GET /api/v1/oseas/layers/flood_reference/geojson?eventKey=FL-20231121-KEN-03
GET /api/v1/oseas/layers/hydrography/geojson?type=lake
GET /api/v1/oseas/layers/coverage/geojson
GET /api/v1/oseas/layers/asset_exposure/geojson
GET /api/v1/oseas/layers/wind_resource
GET /api/v1/oseas/administrative/county/{county-uuid}/summary
```

GeoJSON response shape:

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "id": "uuid",
    "geometry": {"type": "Polygon", "coordinates": []},
    "properties": {"hazardType": "flood", "evidenceKind": "modeled", "confidence": null}
  }],
  "pagination": {"total": 1, "limit": 100, "offset": 0},
  "spatialReference": "EPSG:4326"
}
```

`400 INVALID_BBOX`, `400 INVALID_ID`, `400 INVALID_LEVEL`, `404 NOT_FOUND` and database/schema errors use the standard error envelope. In production, every `/api/v1/oseas/*` route requires a Supabase Auth access token in `Authorization: Bearer <token>`; the backend validates it with Supabase Auth. `SUPABASE_SERVICE_ROLE_KEY` is server-side only and is never returned by the API. In development, routes are open unless `OSEAS_REQUIRE_AUTH=true`.

Only outputs with implemented source/processing adapters and stored evidence are served as layers. The 2023 flood reference and river/lake layers are available after applying the additive schema and ingesting those assets. Climate/terrain/heat/fire/population rasters and validated scores remain unassessed until their processors produce evidence; empty tables must not be displayed as zero risk.
