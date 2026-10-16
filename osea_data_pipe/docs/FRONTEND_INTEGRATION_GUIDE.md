# Frontend integration

The React application in `frontend/` reads the OSEAS API at `/api/v1/oseas`. It does not connect directly to PostGIS. API requests return JSON or EPSG:4326 GeoJSON and use explicit assessment states; see [`API_CONTRACTS.md`](API_CONTRACTS.md) for the complete route reference.

## Local configuration

The frontend Vite proxy defaults to the deployed API. To point it at a locally running backend:

```powershell
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:3000"
npm run dev
```

Do not add database URLs, service-role keys or Earth Engine credentials to frontend variables. Production deployments must allow the frontend origin through backend CORS and must configure the backend authentication policy.

## Map data

The frontend loads map-ready feature data from OSEAS GeoJSON endpoints. Common examples:

```text
GET /layers?includeCounts=true
GET /assets?type=primary_substation&bbox=west,south,east,north&limit=100
GET /layers/asset_exposure/geojson?bbox=west,south,east,north&limit=100
GET /layers/vulnerability_summaries/geojson?bbox=west,south,east,north&limit=100
GET /layers/prithvi_national_summaries/geojson?bbox=west,south,east,north&limit=100
```

`bbox` is west,south,east,north in EPSG:4326. Paginated endpoints expose exact totals. When selecting assets or administrative units, use their stable identifiers to load the corresponding evidence endpoint; do not infer values from rendered marker or polygon colors.

## Live Earth Engine tile layers

`GET /gee-map-layers` requests short-lived tile templates for supported configured Earth Engine assets and public image collections. A caller can pass `?layer={layerId}` to request one layer at a time. The backend creates tile URLs using its Earth Engine identity. Keep these URLs on the server-to-client response only as needed for display; do not log them or persist their temporary credentials.

Web tile layers provide visualization. They do not provide queryable feature attributes, pixel identify, or zonal statistics. Feature popups and pixel values must come from an actual feature query or supported identify/query service. Do not read a raster value from its screen color.

## Interpretation

- `not_assessed` means no usable persisted assessment is available for the requested scope; it does not mean zero hazard.
- Rainfall, temperature, radiance, a flood candidate, and an asset-exposure intersection are distinct types of evidence.
- Show source periods, units, coverage, method and limitations when present.
- Do not call a candidate polygon confirmed flooding or exposure a failure probability.
- Keep catalog metadata distinct from live tile availability and persisted processing status.

For source semantics see [`DATA_CATALOG.md`](DATA_CATALOG.md); for frontend setup see [`../../frontend/README.md`](../../frontend/README.md).
