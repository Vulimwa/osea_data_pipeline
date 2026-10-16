# OSEAS: climate risk and energy infrastructure vulnerability

OSEAS is an open-source, satellite-enabled geospatial intelligence system for helping energy planners understand how climate hazards may affect energy infrastructure in Kenya. It combines climate data, terrain, infrastructure inventories and observed environmental change to produce traceable evidence for investigation and planning.

The project includes multiple related but distinct components: the OSEAS data pipeline and application in this repository, the Energy Infrastructure Vulnerability Dataset workflow in the [climate-risk-infrastructure-vulnerability repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability), and the separately processed CGF-ACI Google Earth Engine demo documented in [CGF_ACI.md](CGF_ACI.md). The CAT model is implemented in the linked vulnerability-workflow repository; its data is held in the same database used by this project. CGF-ACI is not that CAT model and has not yet been integrated as an OSEAS pipeline stage.

## The problem

Energy planners need to understand how climate hazards threaten energy infrastructure. Knowing where hazards and assets are located does not necessarily reveal which assets are most vulnerable, what evidence supports an assessment, or which preventive actions should be prioritised. Detailed engineering and operational data may also be unavailable, particularly for decentralised energy systems.

## The solution

OSEAS combines climate observations, hazard evidence, terrain and energy-infrastructure data in a reproducible geospatial workflow. It stores spatial data and derived evidence in PostgreSQL/PostGIS, provides read-oriented APIs, and presents map and evidence views through a React application using the ArcGIS Maps SDK.

The system is intended to help users investigate risk hotspots, inspect supporting evidence and uncertainty, and compare potential resilience interventions. It distinguishes source observations, modeled hazard evidence, spatial exposure and interpretation; these are not interchangeable. For example, rainfall is not a flood extent, a model candidate is not confirmed inundation, and an asset's intersection with a hazard layer is not a prediction of equipment failure.

## Primary users

Energy planners and infrastructure-resilience teams working for energy agencies, utilities, mini-grid operators, and county or national governments. They can use the system to identify assets for further inspection, compare evidence and prioritize where resilience investments may be valuable.

## Secondary beneficiaries

Communities, health facilities, schools, agricultural businesses and water services that depend on reliable electricity. They benefit indirectly when better-informed planning helps protect energy services.

## What makes it different?

The Energy Access Explorer already supports geospatial energy planning by combining energy supply, demand, infrastructure and socioeconomic information. Combining datasets on a map is therefore not, by itself, a novel contribution.

OSEAS's proposed differentiator is its traceable evidence chain:

**Satellite observation → climate exposure → asset vulnerability → confidence and uncertainty → prioritised intervention**

That distinction must be demonstrated through a reproducible pipeline, measurable model performance and useful decision outputs, not simply asserted. Satellite imagery can help detect environmental hazards and changes around assets, but it cannot independently establish transformer condition, battery degradation or actual outage probability. Those require additional engineering and operational evidence.

## Project components and current scope

- **OSEAS pipeline and application (this repository):** source registration and ingestion, geospatial processing, PostGIS persistence, read-only APIs and an ArcGIS-based map/evidence interface. Available products and run status vary by source; consult the [data catalog](osea_data_pipe/docs/DATA_CATALOG.md) and latest run records.
- **Energy Infrastructure Vulnerability Dataset and CAT model:** implemented in the [separate vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). Its data is in the same database used by OSEAS. See that repository for its methods, outputs and limits; do not treat it as code implemented in this repository.
- **CGF-ACI GEE demo:** processed separately in Google Earth Engine with hosted raster and vector outputs. It is not the CAT model, is not an OSEAS pipeline stage, and its hosted layers are not automatically OSEAS assessment records. See the [CGF-ACI technical note](CGF_ACI.md).
- **Flood screening in this repository:** Sentinel-1 change screening and Prithvi-EO water/flood candidate workflows provide evidence for review. Neither should be presented as confirmed inundation or as a damage/outage estimate.

The Kano Plains map is a pilot view, not evidence of national coverage. Read the [Kano flood/CAT status note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md) for how the screening, CAT model and CGF-ACI work relate.

## Deliverables

1. A reusable GIS vulnerability dataset that addresses the challenge brief.
2. A reproducible Python and remote-sensing pipeline that ingests multiple datasets and documents how results were generated.
3. An interactive ArcGIS Maps SDK and Calcite application that lets planners inspect evidence, compare assets and explore interventions.

## Limits and responsible interpretation

The project does not claim a validated national probability of grid failure, a complete current census of Kenyan energy assets, verified electrical connections based on proximity, or confirmed flooding from screening candidates. Do not infer outages, monetary losses, or asset condition without appropriate supporting data. Check each result's source, date, spatial coverage, run status, assumptions and confidence before using it.

## Documentation

Start with the [OSEAS pipeline README](osea_data_pipe/README.md). It links to the [architecture](osea_data_pipe/docs/ARCHITECTURE.md), [data catalog](osea_data_pipe/docs/DATA_CATALOG.md), [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), [model card](osea_data_pipe/docs/MODEL_CARD.md), [Kano flood/CAT status note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md), [pipeline runbook](osea_data_pipe/docs/END_TO_END_RUNBOOK.md), [API contracts](osea_data_pipe/docs/API_CONTRACTS.md) and [frontend guide](osea_data_pipe/docs/FRONTEND_INTEGRATION_GUIDE.md).
