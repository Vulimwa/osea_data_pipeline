# OSEAS pipeline overview

This overview introduces the processing path. For exact command options and recovery guidance, use the [end-to-end runbook](END_TO_END_RUNBOOK.md); for stage-level requirements, use [pipeline contracts](PIPELINE_CONTRACTS.md).

## 1. Configure and inspect sources

Earth Engine asset IDs and service credentials are configured outside source control. Public climate products and local reference files have separate adapters. The shared registry is [`../config/data_catalog.json`](../config/data_catalog.json). Run the catalog audit and Earth Engine asset audit to check availability, but remember that an audit is not ingestion.

## 2. Ingest source features

The paged importer reads supported Earth Engine feature collections and writes normalized assets, critical services, administrative boundaries and contextual features to PostGIS. Stable source identifiers and upserts support safe retries. Run and dataset-version records capture source and ingestion status.

## 3. Assign spatial context

Assets are related to county and ward geometries. Point-in-area assignment is distinct from line or polygon intersection. Administrative assignment supports reporting; it does not prove that a particular asset serves a particular community.

## 4. Process hazard and climate evidence

Each source has an individual processor and acceptance criteria. Examples include CHIRPS event-window rainfall summaries, NASA POWER heat indicators, VIIRS nighttime-light context, WorldPop population exposure, FIRMS fire detections and bounded flood screening. Some sources are catalog-only or audit-only; check their current run state before describing them as outputs.

## 5. Assess and summarize

Assessment runs connect measured evidence to assets and reporting units. Missing or unverified dimensions remain explicit. A composite score is not emitted merely because component tables or map layers exist.

## 6. Serve and inspect

The Express API exposes read-only JSON and GeoJSON under `/api/v1/oseas`. The frontend uses these endpoints for map layers, selection and evidence detail. Live Earth Engine tile layers, where configured, are visual services and do not replace persisted feature-query or pixel-identify workflows.

## Operational rule

Check `/api/v1/oseas/readiness`, recent run status and quality records before presenting a source as current or complete. A `partial` run means some processing succeeded and some did not; a registered source is not the same as a persisted assessment.

See [`docs/README.md`](README.md) for the documentation index.
