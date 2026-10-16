# Climate Risk & Energy Infrastructure Vulnerability

This project addresses the [OSEAS 2026 Climate Risk & Energy Infrastructure Vulnerability challenge](https://github.com/EnAccess/oseas26-climate-risk-infrastructure-vulnerability). Its goal is to assess how climate-related hazards affect the reliability and resilience of centralized and decentralized energy infrastructure, and to provide planners with GIS evidence they can inspect and use to guide further investigation.

The work is split across related but distinct components: the OSEAS data pipeline and application in this repository, the Energy Infrastructure Vulnerability Dataset and CAT workflow in the [vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability), and the separately processed CGF-ACI Google Earth Engine demo documented in [CGF_ACI.md](CGF_ACI.md). The CAT model is implemented in the linked vulnerability-workflow repository, and its data is held in the same database used by this project. CGF-ACI is a different analysis; it is not the CAT model and is not yet an OSEAS pipeline stage.

## Challenge problem and goal

Flooding, extreme heat, wildfire, drought and severe storms can affect energy infrastructure, including transmission and distribution networks, substations, power plants and mini-grids. Yet knowing where hazards and assets are located does not by itself show which assets are most vulnerable, what evidence supports that assessment, or where preventive action should come first. Detailed condition, network-dependency and outage data can also be scarce, especially for decentralized systems.

The challenge calls for an Energy Infrastructure Vulnerability Dataset in GIS format, with indicators such as flood exposure, heat stress, wildfire exposure, infrastructure criticality, service reliability risk and grid resilience. The analysis is intended to help planners identify hotspots and prioritize resilience work. Results need to be traceable and interpreted in light of their data coverage and assumptions.

## Our solution

We are building an open-source, satellite-enabled geospatial intelligence system that brings climate observations, terrain, energy infrastructure and observed environmental change into reproducible spatial workflows. The OSEAS pipeline stores spatial data and derived evidence in PostgreSQL/PostGIS, exposes read-oriented APIs, and provides an interactive React application using the ArcGIS Maps SDK. The separate vulnerability workflow produces GIS outputs for asset-level screening. Together, these components are intended to help planners inspect risk hotspots, understand the evidence and uncertainty, and consider where resilience interventions may be worth investigating.

The workflow distinguishes observations, modeled hazard evidence, spatial exposure and vulnerability interpretation. They are not interchangeable: rainfall is not a flood extent, a model candidate is not confirmed inundation, and an asset's intersection with a hazard layer is not a prediction of equipment failure.

## What we have achieved

- Built repeatable source registration, audit and ingestion workflows for energy assets, administrative boundaries, critical services and selected climate and hazard datasets.
- Implemented geospatial processing and PostGIS persistence, with read-oriented APIs for catalog and readiness information, runs, assets, assessments and map layers.
- Developed an ArcGIS-based map and evidence interface for exploring available spatial outputs.
- Implemented flood screening workflows in this repository using Sentinel-1 change evidence and Prithvi-EO water/flood candidates. These support investigation; they are not ground truth or damage estimates.
- Implemented the Energy Infrastructure Vulnerability Dataset and CAT workflow in the [separate vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). Its GIS output schema includes flood, heat and wildfire exposure, infrastructure criticality, service reliability risk and a grid resilience score, with Parquet and GeoJSON outputs. Its documented real-data run is a Kano Plains/Nyando pilot, not a national assessment: 64 of 64 assets fell inside the input rasters, flood exposure ranged from 0 to 0.600, and heat and wildfire remained unknown in that run. See that repository for configuration, methods, outputs and validation limits.
- Processed a separate CGF-ACI climate-exposure demo in Google Earth Engine and hosted its raster and vector outputs. This work is distinct from the CAT model and is not yet integrated as an OSEAS pipeline stage.

The pilot results are bounded by their study area and input data. They should not be generalized to all of Kenya or presented as validated loss or outage estimates.

## Primary users

Energy planners and infrastructure-resilience teams working for energy agencies, utilities, mini-grid operators, and county or national governments. They can use the system to identify assets for further inspection, compare evidence and prioritize where resilience investments may be valuable.

## Secondary beneficiaries

Communities, health facilities, schools, agricultural businesses and water services that depend on reliable electricity. They benefit indirectly when better-informed planning helps protect energy services.

## Why this solution stands out

The Energy Access Explorer already supports geospatial energy planning by combining energy supply, demand, infrastructure and socioeconomic information. Combining datasets on a map is therefore not, by itself, a novel contribution.

Our differentiator is the evidence chain connecting:

**Satellite observation → climate exposure → asset vulnerability → confidence and uncertainty → prioritised intervention**

In practical terms, the work combines reusable GIS outputs, documented processing and an application for examining evidence rather than presenting an unexplained risk score. It also makes boundaries visible: source periods and coverage matter, unknown inputs stay unknown, and screening evidence is not described as a confirmed impact. The distinct CAT workflow and OSEAS data platform share a database while remaining separately implemented; the CGF-ACI demo is documented separately rather than being presented as a production pipeline component.

This is how the project aims to stand out; demonstrating it fully requires continued validation against independent observations and useful decision outcomes. Satellite imagery can help identify environmental hazards and changes near assets, but it cannot independently establish transformer condition, battery degradation or actual outage probability. Those need additional engineering and operational evidence.

## Technology and data

The project uses Python for data processing and geospatial analysis, Earth Engine and satellite/climate sources for selected observations, PostgreSQL/PostGIS for spatial storage and queries, and a React application with the ArcGIS Maps SDK for interactive map and evidence views. The vulnerability workflow also provides GIS outputs in Parquet and GeoJSON. Dataset status, coverage, resolution and implementation notes are documented in the [data catalog](osea_data_pipe/docs/DATA_CATALOG.md); a catalog entry does not necessarily mean a source has a successful current run.

## Limits and responsible interpretation

The project does not claim a validated national probability of grid failure, a complete current census of Kenyan energy assets, verified electrical connections based on proximity, or confirmed flooding from screening candidates. Do not infer outages, monetary losses or asset condition without appropriate supporting data. Check each result's source, date, spatial coverage, run status, assumptions and confidence before using it.

## Documentation

Start with the [OSEAS pipeline README](osea_data_pipe/README.md). It links to the [architecture](osea_data_pipe/docs/ARCHITECTURE.md), [data catalog](osea_data_pipe/docs/DATA_CATALOG.md), [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), [model card](osea_data_pipe/docs/MODEL_CARD.md), [Kano flood/CAT status note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md), [pipeline runbook](osea_data_pipe/docs/END_TO_END_RUNBOOK.md), [API contracts](osea_data_pipe/docs/API_CONTRACTS.md) and [frontend guide](osea_data_pipe/docs/FRONTEND_INTEGRATION_GUIDE.md).
