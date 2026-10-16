# OSEAS API contracts

Base path: `/api/v1/oseas`. Routes are read-only; processing is started through CLI commands in [`END_TO_END_RUNBOOK.md`](END_TO_END_RUNBOOK.md). Errors follow `{ "error": { "code", "message", "details", "correlation_id" } }`. GeoJSON coordinates use longitude/latitude in EPSG:4326. Database `NULL` values remain JSON `null`; absent assessments use explicit states such as `not_assessed` or `insufficient_data`.

## Routes

| Method and path | Query/body | Response |
|---|---|---|
| `GET /readiness` | None | DB/PostGIS connectivity, source-import run, inventory/output table presence, latest usable flood run plus latest attempt, separate heat/fire/nightlights/rainfall/population availability, and Prithvi state. Nightlight counts use the Black Marble dataset key; rainfall counts use persisted CHIRPS event summaries. `apiReadyForIntegration` is false until the complete OSEAS schema is installed; it does not mean hazards are scientifically validated. |
| `GET /catalog` | None | Machine registry data, access method, coverage, temporal range, units, attribution, evidence kind, retrieval state and last successful persisted retrieval. |
| `GET /raster-registry` | None | Raster metadata derived from `config/data_catalog.json`, including registered source, bands, units, display settings and observation-period metadata where supplied. Registration is not proof of successful retrieval, tile availability or analytical query support. |
| `GET /gee-map-layers` | Optional `layer={layerId}` | Generates Earth Engine tile templates for the four configured hackathon output assets and supported VIIRS, CHIRPS, ERA5-Land and ERA5 imagery. The backend authenticates to Earth Engine; credentials are not returned. Requires backend Earth Engine access. Tiles are visual layers, not queryable FeatureLayers or pixel-identify results. Omitting `layer` requests the four configured assets; pass a supported layer ID to request one asset or one image-collection visualization. |
| `GET /runs?limit=100&offset=0` | limit 1–500; offset >=0 | OSEAS ingestion/processing runs with model diagnostics when linked. |
| `GET /runs/{uuid}` | UUID path | One processing run plus quality checks. `404 NOT_FOUND` if absent. |
| `GET /layers` | Optional `includeCounts=true` | Registered map endpoints plus stored hazard evidence types. By default, stored derived layers report `status=queryable` without claiming whether rows exist. With `includeCounts=true`, exact `featureCount`, `hasData`, and `available`/`not_assessed` status are included. GeoJSON endpoints provide exact filtered totals in `pagination.total`. `count` is the number of catalog entries. |
| `GET /layers/flood_candidate/geojson?bbox=west,south,east,north&limit=100&offset=0` | Optional EPSG:4326 bbox; limit 1–500 | RFC 7946-style `FeatureCollection`, `pagination.total`, processing run, and `spatialReference`. Returns an empty collection with `status=not_assessed` before the first successful flood run. Feature properties include evidence kind, event dates, source, confidence (null for uncalibrated baseline), and method/quality metadata. |
| `GET /assets?type=distribution_transformer&sourceDataset=osm_kano_pilot&wardId={uuid}&countyId={uuid}&bbox=...&limit=100&offset=0` | Optional type, source dataset key, one admin ID, bbox and pagination | Asset `FeatureCollection`, source identifiers/properties and pagination. Bbox is lon/lat. `sourceDataset=osm_kano_pilot` isolates the Nyando/Kano screening pilot from the national inventory. |
| `GET /assets/{uuid}/exposure` | UUID path | Asset hazard evidence, periods, exposed status, measured intersection, method provenance and processing run. A score published in provenance is also returned as `exposureScore`, with `exposureScoreStatus=pilot_screening` and `scoringScope` for the Kano pilot. No rows returns `status=not_assessed`; hazards marked `not_assessed` have a null score. |
| `GET /assets/{uuid}/criticality` | UUID path | Evidence-backed criticality assessments and explicit missing inputs. Returns `unknown` when verified served load, network role or redundancy evidence is insufficient; no fabricated score is returned. |
| `GET /assets/{uuid}/service-dependencies` | UUID path | Verified/candidate/unknown service relationship assessments, source service attributes, evidence, confidence basis and processing run. Proximity alone never creates a verified relationship. |
| `GET /layers/nightlights/geojson?bbox=west,south,east,north&limit=100&offset=0` | Optional EPSG:4326 bbox and pagination | NASA Black Marble VNP46A2 daily images are quality screened and summarized monthly through Earth Engine. One feature per zone carries `radianceMetrics` (recent median, baseline median, percent change), units, selected periods, valid-month coverage, quality rule, source image counts, checksum, and zone type. No rows is `not_assessed`; zero radiance is retained as an observed zero. |
| `GET /layers/rainfall/geojson?bbox=west,south,east,north&limit=100&offset=0` | Optional EPSG:4326 bbox and pagination | Event-reference-driven CHIRPS summaries, one feature per county/ward and variable: 30-day rainfall total, absolute anomaly and (when baseline is positive) percentage anomaly against the same calendar window in 2001–2020. Properties include event date, image coverage, valid baseline years, method and interpretation limits. Requires dated flood references and persisted administrative boundaries; no rows means `not_assessed`, not zero rainfall. |
| `GET /layers/vulnerability_summaries/geojson?bbox=west,south,east,north&limit=100&offset=0` | Optional EPSG:4326 bbox and pagination | Current ward and county evidence summaries with asset denominators, hazard exposure counts, missing-evidence provenance, and explicit withheld composite score. |
| `GET /assets/{uuid}/vulnerability` | UUID path | Persisted asset vulnerability assessments and provenance, or `status=not_assessed`. A score is included only when it exists in a persisted assessment; missing evidence is not converted to zero. |
| `GET /layers/asset_vulnerability/geojson?sourceDataset=osm_kano_pilot&bbox=west,south,east,north&limit=100&offset=0` | Optional source dataset, EPSG:4326 bbox and pagination | Map-ready asset vulnerability features. Pilot scores include `scoreStatus=pilot_screening` and `scoringScope=kano_plains`; missing or withheld scores remain null and explicitly labeled. |
| `GET /administrative/{ward\|county}/{uuid}/summary` | Boundary level and UUID | Boundary as a GeoJSON `Feature` with latest hazard-screen record, national Prithvi pixel totals/area/coverage when that source produced the record, and a ward/county `vulnerabilitySummary`. Pixel values are null with `pixelStatsStatus=not_assessed` for records without those measurements. Missing vulnerability summary returns `not_assessed`; no composite score is implied. |
| `GET /layers/prithvi_national_summaries/geojson?eventFingerprint={sha256}&bbox=...&limit=100&offset=0` | Optional 64-character event fingerprint, EPSG:4326 bbox and pagination. Omit fingerprint to use the latest completed/partial run. | Map-ready county/ward GeoJSON with total/valid/candidate pixels, candidate area/fraction, valid coverage, explicit candidate-evidence status, and model/run provenance. Missing output is `not_assessed`; candidate pixels are not confirmed flood extent or asset exposure. |
| `GET /priorities?limit=100&offset=0` | Pagination | Existing reviewed/candidate intervention records, including field-verification recommendations; empty list returns `status=not_assessed`. These are not simulated CAT or intervention outcomes. See [`SCENARIO_CAT_MODEL.md`](SCENARIO_CAT_MODEL.md). |
| `GET /layers/flood_reference/geojson?eventKey=FL-20231121-KEN-03&bbox=...&limit=100&offset=0` | Optional event key, EPSG:4326 bbox and pagination | Source-preserving reference polygons with original properties, event/run provenance, geometry-measured area, and separately attributed event-level reported area/population. Reference evidence remains separate from model candidates. |
| `GET /layers/hydrography/geojson?type=river\|lake&bbox=...&limit=100&offset=0` | Optional type, bbox and pagination | Mappable rivers/lakes with source identifiers/properties and ingest run. Source GeometryCollections are preserved. |
| `GET /layers/population_exposure/geojson?eventKey=...&reportingUnitId={uuid}&status=assessed&bbox=...&limit=100&offset=0` | Optional event key, reporting-unit UUID, status, bbox and pagination | WorldPop estimated residents within an observed flood footprint. `populationPotentiallyExposed` is an estimated person count; `populationTotal` remains null until a full-unit denominator is implemented. Evidence carries population year, source checksum, valid-raster fraction, method and interpretation limits. |
| `GET /layers/{climate_observations\|climate_projections\|terrain\|land_cover\|fire\|asset_exposure\|asset_vulnerability\|asset_criticality\|service_dependencies\|administrative_summaries\|interventions\|population_exposure\|grid_resilience\|coverage}/geojson?bbox=...&limit=100&offset=0` | Registered layer key; optional EPSG:4326 bbox and pagination. Asset-derived layers also accept `sourceDataset=osm_kano_pilot`. | Common map-ready GeoJSON from durable output records. Empty output returns `status=not_assessed`; properties retain method, source, run, coverage and uncertainty fields that exist for that output. The source filter isolates the pilot records from national inventory rows. |
| `GET /layers/wind_resource` | None | Cache manifest with GeoTIFF URLs, units, CRS, bounds, dimensions, checksums and retrieval metadata; returns `not_cached` plus sync command before download. These layers show resource context, not wind hazards. |
| `GET /layers/wind_resource/{wind_speed_10m\|power_density_10m\|air_density_10m}/geotiff` | Product ID path | Cached GeoTIFF bytes (`image/tiff`) for GeoTIFF-capable map clients. Populate with `npm run oseas:wind:sync`. |

## Examples

```http
GET /api/v1/oseas/readiness
GET /api/v1/oseas/assets?type=primary_substation&bbox=36.7,-1.4,37.0,-1.1&limit=50
GET /api/v1/oseas/assets?sourceDataset=osm_kano_pilot&bbox=34.60,-0.40,35.30,0.10&limit=100
GET /api/v1/oseas/assets/{asset-uuid}/exposure
GET /api/v1/oseas/assets/{asset-uuid}/vulnerability
GET /api/v1/oseas/layers/flood_candidate/geojson?bbox=36.7,-1.4,37.0,-1.1
GET /api/v1/oseas/layers/flood_reference/geojson?eventKey=FL-20231121-KEN-03
GET /api/v1/oseas/layers/hydrography/geojson?type=lake
GET /api/v1/oseas/layers/coverage/geojson
GET /api/v1/oseas/layers/asset_exposure/geojson
GET /api/v1/oseas/layers/population_exposure/geojson?eventKey=FL20240421KEN
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

`400 INVALID_BBOX`, `400 INVALID_ID`, `400 INVALID_LEVEL`, `404 NOT_FOUND` and database/schema errors use the standard error envelope. In production, `/api/v1/oseas/*` routes require a Supabase Auth access token by default; the backend validates it with Supabase Auth. `OSEAS_PUBLIC_READ_API=true` is an opt-in exception that makes `GET` routes public, while non-GET requests remain authenticated. `SUPABASE_SERVICE_ROLE_KEY` is server-side only and is never returned by the API. In development, routes are open unless `OSEAS_REQUIRE_AUTH=true`.


Only routes with implemented source/processing paths are served. Whether a route currently has data depends on its latest successful run and filters. Catalog metadata and successful live tile generation do not by themselves establish persisted analytical results. Empty or unassessed outputs must not be displayed as zero risk.
