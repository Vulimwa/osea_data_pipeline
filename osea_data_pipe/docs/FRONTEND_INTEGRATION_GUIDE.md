# Frontend integration guide

Base URL: `/api/v1/oseas`. Routes require a Supabase access token when `OSEAS_REQUIRE_AUTH=true`; send `Authorization: Bearer <access_token>`. Coordinates and bbox filters use EPSG:4326. GeoJSON layers return `FeatureCollection`, pagination, and an explicit status. `not_assessed` means no stored result; it must not be styled as zero hazard.

## Initial map wiring

1. Call `GET /readiness` and `GET /catalog` to show backend/schema state and source attribution.
2. Call `GET /layers` to enumerate map routes; stored derived layers report `queryable` without making a claim about whether rows exist. Request `?includeCounts=true` when exact `featureCount`, `hasData`, and `available`/`not_assessed` state are needed; map queries already return filtered totals.
3. Load available source/reference features with `GET /layers/flood_reference/geojson?eventKey=...` or `GET /layers/hydrography/geojson?type=river|lake`.
4. Load model candidates with `GET /layers/flood_candidate/geojson?bbox=west,south,east,north`.
5. Load exposure summaries with `GET /layers/asset_exposure/geojson?sourceDataset=osm_kano_pilot&bbox=...`, pilot asset vulnerability with `GET /layers/asset_vulnerability/geojson?sourceDataset=osm_kano_pilot&bbox=...`, ward/county screening with `GET /layers/vulnerability_summaries/geojson?bbox=...`, and population estimates with the filters below.
6. For an asset, call `GET /assets/{uuid}/exposure`, `/criticality`, `/service-dependencies`, and `/vulnerability`. An empty or unknown result is unassessed/insufficient evidence, not low risk.
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
- `GET /layers/nightlights/geojson?bbox=...&limit=100&offset=0`
- `GET /layers/vulnerability_summaries/geojson?bbox=...&limit=100&offset=0`
- `GET /catalog` includes provider, temporal/spatial coverage, units, attribution, adapter and retrieval status.

## Nighttime lights

The `nightlights` layer contains one feature per administrative unit, energy asset, or critical service with `radianceMetrics.NTL_RECENT_MEDIAN_RADIANCE`, `radianceMetrics.NTL_BASELINE_MEDIAN_RADIANCE`, and `radianceMetrics.NTL_MEDIAN_CHANGE_PERCENT`. Admin statistics are polygon summaries located at an interior representative point; asset/service statistics summarize a documented 500 m context buffer around a representative point. Read `unit`, `recentPeriod`, `baselinePeriod`, `recentValidMonthFraction`, `baselineValidMonthFraction`, quality exclusions, and provenance from feature properties. A zero metric with valid months is an observed zero; a null metric or zero valid-month fraction means insufficient observations. Change is a contextual signal for investigation. It does not show grid connection, feeder dependency, outage duration, or damage.

This layer is stored from monthly composites of NASA Black Marble VNP46A2 daily imagery in Earth Engine. Each composite uses only `Mandatory_Quality_Flag == 0`; selected dates, monthly source image counts, valid-month coverage, and the quality rule are stored in provenance. The data can contain fire, gas-flare, observation, and other human-activity signals.

Only documented routes backed by stored records should be shown as available. The readiness response reports heat, fire, nighttime lights, and population exposure separately. `not_assessed` means no stored result, while a blocked source reports its credential or configuration requirement. Ward/county vulnerability summaries report assessed denominators and evidence gaps; they do not show validated numeric risk scores. Criticality, resilience and intervention records express evidence status; they do not become validated numeric rankings when required topology, outage history, engineering criteria, or intervention benefit evidence is missing. Rainfall anomaly, Landsat LST, burned-area, future projection and Kenya-specific validation outputs remain outstanding. See [implementation status](IMPLEMENTATION_STATUS.md) and [API contracts](API_CONTRACTS.md).
