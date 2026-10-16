# OSEAS architecture

OSEAS turns source datasets into traceable spatial evidence. Processing is separated from presentation: Python and Earth Engine jobs write durable results to PostgreSQL/PostGIS; the Express API reads and serves those results; the React application displays them using the ArcGIS Maps SDK.

## Data flow

```text
Earth Engine assets ─┐
Climate APIs/raster ─┼─> audit and source adapters
Reference datasets ──┘           |
                                 v
                    Earth Engine / Python GIS processing
                                 |
                                 v
   PostgreSQL/PostGIS: source inventory, boundaries, evidence,
   exposure, processing runs, versions, coverage and quality
                                 |
                                 v
          Express read API: /api/v1/oseas/*
                                 |
                                 v
          React + ArcGIS Maps SDK frontend
```

## Main components

- **Source registry:** `config/data_catalog.json` describes provider, access method, units, periods, spatial coverage, attribution and retrieval state. Registry presence does not mean that a source was downloaded, processed or persisted.
- **Earth Engine ingestion:** `oseas.ingest` audits configured table assets, reads bounded pages, normalizes supported geometries and upserts source features using stable keys.
- **Processors:** Python modules and scripts implement source-specific rainfall, heat, fire, population, wind-resource and flood workflows. Each processor has its own prerequisites and evidence contract.
- **Spatial database:** `database/schema.sql` defines source inventory, administrative units, spatial assignments, model outputs, assessments, provenance and run-quality tables.
- **API:** `src/` exposes validated read-only JSON and GeoJSON endpoints. Processing is run through commands, not API requests.
- **Frontend:** `frontend/` contains the map and evidence screens. It consumes the API rather than querying PostGIS directly.
- **Live GEE tiles:** the map layer endpoint can generate short-lived tile templates server-side for configured Earth Engine assets. Tile display is not a feature query or pixel-identify operation.

## Processing and persistence

Earth Engine calculations are generally performed remotely. Feature pages and bounded vector outputs are persisted to PostGIS rather than downloading complete raster collections into the API process. Raster workflows use source-specific acquisition/processing paths and record their own checksums, coverage and method details where implemented.

Ingestion uses deterministic source identifiers, page-level writes and database uniqueness constraints to make reruns idempotent. It does not delete source records that disappear upstream. Assessment runs retain their own provenance and status.

## Spatial semantics

- Point assets are assigned to boundaries using `ST_Covers`.
- Lines and polygons are related to administrative units using intersections. Where supported, line length or polygon area is measured on the clipped geometry.
- Spatial intersection indicates geographic overlap only. It does not establish electrical connectivity or service dependency.
- Map output GeoJSON uses longitude/latitude coordinates in EPSG:4326.

## Interpretation boundaries

The system keeps source observations, modeled hazard candidates, measured exposure and assessment interpretation separate. Sentinel-1 and Prithvi flood outputs are candidates, not confirmed flood extents. Asset exposure is not a failure probability. Vulnerability, criticality and resilience dimensions remain unknown or withheld when their required inputs are absent.

See [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md) for calculation details and [`PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md) for stage acceptance rules.
