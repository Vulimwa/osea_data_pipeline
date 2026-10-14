# Frontend integration guide

Base URL: `/api/v1/oseas`. Routes require a Supabase access token when `OSEAS_REQUIRE_AUTH=true`; send `Authorization: Bearer <access_token>`. Coordinates and bbox filters use EPSG:4326. GeoJSON layers return `FeatureCollection`, pagination, and an explicit status. `not_assessed` means no stored result; it must not be styled as zero hazard.

## Initial map wiring

1. Call `GET /readiness` and `GET /catalog` to show backend/schema state and source attribution.
2. Call `GET /layers` to enumerate map layers currently registered in the API.
3. Load available source/reference features with `GET /layers/flood_reference/geojson?eventKey=...` or `GET /layers/hydrography/geojson?type=river|lake`.
4. Load model candidates with `GET /layers/flood_candidate/geojson?bbox=west,south,east,north`.
5. Load exposure summaries with `GET /layers/asset_exposure/geojson?bbox=...` and population estimates with the filters below.
6. For an asset, call `GET /assets/{uuid}/exposure` and `GET /assets/{uuid}/vulnerability`. An empty vulnerability response is unassessed, not a low score.
7. Show run provenance through `GET /runs?limit=100&offset=0` and `GET /runs/{uuid}`.

## Population exposure layer

`GET /layers/population_exposure/geojson?eventKey=FL20240421KEN&reportingUnitId={uuid}&status=assessed&bbox=west,south,east,north&limit=100&offset=0`

All filters are optional. `eventKey` filters the event key recorded in evidence. `reportingUnitId` selects one ward/county row; omit it to include event-level and administrative features. `status` accepts `assessed`, `partial`, `unknown`, or `not_assessed`. `bbox` is west,south,east,north. Limit is 1–500.

Population feature properties include:

| Field | Meaning |
|---|---|
| `populationPotentiallyExposed` | Sum of valid WorldPop estimated persons-per-pixel cells with centers inside the event footprint or event/admin intersection. Null means no valid raster cells; zero means valid cells summed to zero. |
| `populationTotal` | Null until a separate full administrative population denominator is calculated. |
| `assessmentStatus` | `assessed` when valid raster cells were measured; `unknown` when no valid cells were available. Coverage details in evidence can show partial raster validity. |
| `method` | Current WorldPop method version (`worldpop_cell_center_zonal_sum_v1`). |
| `evidence.populationReferenceYear` | Year of the population surface, default 2024. |
| `evidence.validRasterFraction` | Valid cells divided by raster cells whose centers fell inside the analyzed geometry. |
| `evidence.eventKey`, `eventDates` | Flood-reference event scope and source observation dates. |
| `evidence.sourceRasterSha256` | Checksum of the population raster used. |
| `evidence.limitations` | Interpretation limits and validation state. |

These values estimate residents in a mapped flood footprint. They do not state confirmed impacts, displacement, power service, or asset dependency. Event-level geometry and admin intersections are separate map features. Avoid summing multiple events without handling overlap.

Example response:

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "id": "stable-assessment-uuid",
    "geometry": {"type": "MultiPolygon", "coordinates": []},
    "properties": {
      "populationPotentiallyExposed": 1234.5,
      "populationTotal": null,
      "populationUnit": "estimated persons",
      "assessmentStatus": "assessed",
      "method": "worldpop_cell_center_zonal_sum_v1",
      "evidence": {"populationReferenceYear": 2024, "validRasterFraction": 0.98}
    }
  }],
  "pagination": {"total": 1, "limit": 100, "offset": 0},
  "spatialReference": "EPSG:4326",
  "layer": "population_exposure",
  "status": "available"
}
```

The numbers above illustrate the response shape only; do not present example values as real OSEAS results.

## Other useful routes

- `GET /assets?type=primary_substation&wardId={uuid}&bbox=...&limit=100&offset=0`
- `GET /administrative/{ward|county}/{uuid}/summary`
- `GET /priorities?limit=100&offset=0`
- `GET /layers/coverage/geojson?bbox=...`
- `GET /catalog` includes provider, temporal/spatial coverage, units, attribution, adapter and retrieval status.

Only documented routes backed by stored records should be shown as available. Current heat, rainfall anomaly, fire, criticality, vulnerability, resilience and intervention ranking products are not yet computed; empty result layers should display `not_assessed` or be hidden behind an explicit unavailable state. See [implementation status](IMPLEMENTATION_STATUS.md) and [API contracts](API_CONTRACTS.md).
