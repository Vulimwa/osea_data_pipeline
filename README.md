# OSEAS project scope and deliverables

OSEAS is a spatial evidence pipeline and decision-support application for understanding climate hazards in relation to energy infrastructure in Kenya. This document describes what the repository implements; it is not a future-feature checklist or a claim that every source has current, complete coverage.

## Challenge

Climate observations, hazard products, infrastructure inventories, service locations and administrative boundaries are maintained in separate systems. That makes it difficult to see which assets intersect hazard evidence, compare evidence between places, or know whether a reported result is complete enough to act on.

## Solution

OSEAS connects these sources through repeatable ingestion and geospatial processing. It stores assets and derived evidence in PostgreSQL/PostGIS, serves read-only and provenance-aware APIs, and presents map and evidence views in a React application using the ArcGIS Maps SDK.

The system distinguishes among:

- **Observation:** a value measured or reported by a source, with period and unit.
- **Hazard evidence:** a source or model output indicating a possible hazard condition.
- **Exposure:** a spatial relationship between hazard evidence and an asset or reporting unit.
- **Interpretation:** a conclusion drawn from evidence, with limitations and missing inputs.

These are not interchangeable. For example, rainfall is not a flood extent, a model candidate is not confirmed inundation, and an exposure intersection is not a prediction of equipment failure.

## Delivered capabilities

- Earth Engine feature-asset auditing and paged, idempotent ingestion.
- PostGIS storage for energy assets, critical services, administrative units, hazard evidence, exposure, processing runs, source versions and quality records.
- County/ward spatial assignment and administrative reporting.
- Source-specific CHIRPS rainfall, NASA POWER heat, VIIRS nighttime-lights, FIRMS active-fire and WorldPop population workflows, subject to their individual source/run status.
- Bounded Sentinel-1 flood screening and Prithvi-EO flood/water candidate workflows.
- Read-only API routes for map layers, assets, assessment detail, runs, readiness and source catalog.
- React/ArcGIS map and evidence interfaces for inspecting available spatial outputs.
- A separate CGF-ACI Earth Engine prototype output. Its score is exploratory and is not a validated OSEAS production risk score.

## Documented processing examples

The repository records historical run snapshots, including a CHIRPS run with 7,878 county/ward measurements for two 2024 reference events and a 2024 NASA POWER run with 215,208 observations, 101,987 asset exposure rows and 1,261 county/ward summaries. These numbers describe those runs only. Check the API readiness and latest run records before presenting them as current.

## What the system does not claim

- A validated national probability of grid failure or outage.
- A complete, current census of every Kenyan energy asset.
- Confirmed flooding from Sentinel-1 or Prithvi screening candidates.
- Verified electrical connections based on geographic proximity.
- A national composite vulnerability, criticality or resilience score where required evidence is missing.
- Current retrieval or coverage simply because a dataset appears in the catalog.

## Further reading

Start with the [OSEAS project README](osea_data_pipe/README.md). It links to the [architecture](osea_data_pipe/docs/ARCHITECTURE.md), [data catalog](osea_data_pipe/docs/DATA_CATALOG.md), [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), [model card](osea_data_pipe/docs/MODEL_CARD.md), [pipeline runbook](osea_data_pipe/docs/END_TO_END_RUNBOOK.md), [API contracts](osea_data_pipe/docs/API_CONTRACTS.md), and [frontend guide](osea_data_pipe/docs/FRONTEND_INTEGRATION_GUIDE.md).
