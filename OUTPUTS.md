# OSEAS project scope and deliverables

OSEAS is a spatial evidence pipeline and decision-support application for examining climate hazards alongside energy infrastructure in Kenya. It connects source data, geospatial processing, PostGIS storage, a read-only API and an interactive map.

## What the project delivers

- Repeatable ingestion and audit workflows for energy assets, administrative boundaries, critical services and selected climate and hazard sources.
- Spatial assessments and map-ready outputs with source, period, processing-run and quality context where available.
- Read-only API endpoints for readiness, catalog and raster metadata, runs, assets, assessments and spatial layers.
- A React application using the ArcGIS Maps SDK to inspect available map layers and evidence.
- A separately processed Google Earth Engine CGF-ACI demo with hosted map outputs. Pipeline integration is future work; tile visualization does not make it a persisted OSEAS assessment.

Scenario-based catastrophe modelling, baseline-versus-scenario comparisons and intervention-effect estimates are not current OSEAS capabilities in this checkout. The [scenario/CAT methods note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md) describes the proposed extension and the evidence needed before making impact claims.

## How to interpret results

An observation is not itself a hazard footprint. A hazard intersection is evidence of exposure, not a prediction of equipment failure. A missing assessment or incomplete coverage must not be interpreted as zero risk. Check the latest run and its quality records before describing any source or output as current.

The repository does not claim a validated national grid-failure probability, a complete current inventory of Kenyan energy assets, or verified service dependencies based only on proximity. CGF-ACI is a separately processed exploratory GEE demonstration, not a validated failure model or an OSEAS pipeline result. See the [CGF-ACI technical note](CGF_ACI.md).

## Documentation

For the implementation and operating detail, start with the [OSEAS README](osea_data_pipe/README.md) and [documentation index](osea_data_pipe/docs/README.md). The [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), [model card](osea_data_pipe/docs/MODEL_CARD.md) and [end-to-end runbook](osea_data_pipe/docs/END_TO_END_RUNBOOK.md) explain calculations, limitations and execution.
