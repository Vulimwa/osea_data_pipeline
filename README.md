# Climate Risk & Energy Infrastructure Vulnerability

This project addresses the [OSEAS 2026 Climate Risk & Energy Infrastructure Vulnerability challenge](https://github.com/EnAccess/oseas26-climate-risk-infrastructure-vulnerability). We are building an open-source, satellite-enabled geospatial intelligence system to help energy planners determine which infrastructure deserves attention first, what evidence supports that priority, and what further action can reasonably be taken.

**Project documents:** [README](README.md) · [Outputs](OUTPUTS.md) · [CGF-ACI analysis](CGF_ACI.md) · [OSEAS technical documentation](osea_data_pipe/docs/README.md)

## The problem

Energy planners need to understand how climate hazards threaten energy infrastructure. Knowing where hazards and assets are located does not necessarily show which assets are most vulnerable, what evidence supports an assessment, or which preventive actions should be prioritized. Detailed engineering and operational information may also be unavailable, particularly for decentralized energy systems.

Flooding, extreme heat, wildfire, drought and severe storms can affect power plants, transmission and distribution networks, substations and mini-grids. Planners need more than a map of hazards: they need traceable evidence connecting the hazard to exposed assets and a clear account of uncertainty and missing information.

## The solution

The project brings together climate data, terrain, energy-infrastructure inventories and observed environmental change in reproducible geospatial workflows. It is designed to generate an auditable Energy Infrastructure Vulnerability Dataset and help users investigate hotspots, inspect the evidence and uncertainty behind assessments, and compare potential resilience interventions.

The solution spans two distinct codebases that use the same project database:

- The OSEAS pipeline and application in this repository handle data ingestion and spatial processing, store data and evidence in PostgreSQL/PostGIS, expose read-oriented APIs, and provide an interactive map and evidence interface.
- The Energy Infrastructure Vulnerability Dataset and CAT model are implemented in the [vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). That repository contains the CAT model code; its data is held in the shared database. Refer to it for the model's methods, outputs and validation status.

The project also includes a separate [CGF-ACI Google Earth Engine demo](CGF_ACI.md). CGF-ACI is not the CAT model and is not yet integrated as an OSEAS pipeline stage.

## Who it serves

**Primary users:** energy planners and infrastructure-resilience teams at energy agencies, utilities, mini-grid operators, and county or national governments. They can use the evidence to identify assets for inspection, understand relative risk, and consider where resilience investments may be most valuable.

**Secondary beneficiaries:** communities, health facilities, schools, agricultural businesses and water services that depend on reliable electricity. They may benefit when better-informed planning helps protect energy services.

## Why our solution?

The Energy Access Explorer already supports geospatial energy planning by combining energy supply, demand, infrastructure and socioeconomic information. We do not claim that putting energy datasets on a map is, by itself, novel.

Our solution addresses the step planners still need between seeing hazards on a map and deciding what to investigate or protect. It connects hazard observations to specific centralized and decentralized energy assets, preserves the evidence and assumptions behind each assessment, and makes uncertainty visible. This gives planners a practical way to compare priorities and direct scarce inspection and resilience resources toward assets that warrant closer attention—without disguising incomplete evidence as certainty.

The differentiator is the traceable evidence chain:

**Satellite observation → climate exposure → asset vulnerability → confidence and uncertainty → prioritized intervention**

The aim is not to produce another map showing where climate risk exists. It is to help planners understand why an asset merits attention, compare it with other priorities, and see what the evidence can—and cannot—support. Reproducible processing allows results to be reviewed and updated; visible source periods, coverage, assumptions and missing data make them more useful than an unexplained score. The contribution must be demonstrated through measurable model performance and useful decision outputs, not asserted from the technology stack alone.

Satellite observations can help detect environmental hazards and changes around infrastructure. They cannot independently establish transformer condition, battery degradation or actual outage probability. Those conclusions require additional engineering, network and operational evidence.

See [how the project addresses the hackathon goals](#how-this-addresses-the-hackathon-goals), including the challenge requirements, delivered components and current limits.

## Intended deliverables

1. **A reusable GIS vulnerability dataset** that addresses the challenge brief and supports asset-level investigation.
2. **A reproducible Python and remote-sensing pipeline** that ingests multiple datasets and documents how outputs were produced.
3. **An interactive ArcGIS Maps SDK and Calcite application** that lets planners inspect evidence, compare assets and explore interventions.

## How this addresses the hackathon goals

The [challenge brief's goal](https://github.com/EnAccess/oseas26-climate-risk-infrastructure-vulnerability#abstract-and-goal) is to assess climate-related threats to centralized and decentralized energy infrastructure and support resilience planning. Its [expected outcomes](https://github.com/EnAccess/oseas26-climate-risk-infrastructure-vulnerability#expected-outcomes) call for a GIS vulnerability dataset covering hazard exposure, criticality, service reliability and resilience.

| Hackathon goal | How our solution addresses it |
| --- | --- |
| Map vulnerability across energy assets and services | The separate vulnerability workflow produces per-asset GIS outputs and includes flood, heat and wildfire exposure, criticality, service reliability risk and a grid resilience score. Its documented real-data result is a Kano Plains/Nyando pilot, not a complete national inventory. |
| Combine hazard and infrastructure evidence | The vulnerability workflow uses climate and terrain inputs with energy-asset data; the OSEAS platform provides source ingestion, spatial processing and shared PostGIS storage. The actual method and input coverage vary by run and are documented in the [vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). |
| Make results reproducible and reviewable | Processing code, configuration and GIS outputs are maintained in the relevant repositories. OSEAS stores source and run context where available; users should check dates, coverage, assumptions and confidence before interpreting a result. |
| Help planners use the evidence | The ArcGIS application and APIs expose map layers and assessment information for exploration. These are screening and prioritization aids—not engineering certification, outage prediction or proof of avoided losses. |

This maps the project to the challenge; it does not imply that every hazard is currently assessed, that the pilot represents all of Kenya, or that all planned capabilities are complete.

## What we have achieved

- Built repeatable source registration, auditing and ingestion workflows for energy assets, administrative boundaries, critical services and selected climate and hazard sources.
- Implemented geospatial processing and PostGIS persistence, with read-oriented APIs for catalog/readiness information, processing runs, assets, assessments and spatial layers.
- Developed an ArcGIS-based map and evidence interface for exploring available spatial outputs.
- Implemented Sentinel-1 change screening and Prithvi-EO water/flood candidate workflows in the OSEAS repository. These produce evidence for investigation; they are not confirmed inundation or damage estimates.
- Implemented the Energy Infrastructure Vulnerability Dataset and CAT workflow in the [separate vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). Its GIS output schema includes flood, heat and wildfire exposure, infrastructure criticality, service reliability risk and a grid resilience score, with Parquet and GeoJSON outputs. The documented real-data run is a Kano Plains/Nyando pilot: all 64 assets fell inside the input rasters, flood exposure ranged from 0 to 0.600, and heat and wildfire were unknown in that run. This is a pilot, not a national assessment.
- Processed the separate CGF-ACI climate-exposure demo in Google Earth Engine and hosted its raster and vector outputs. It remains distinct from the CAT model and is not yet an OSEAS pipeline stage.

The pilot findings are bounded by their study area, input data and assumptions. Do not generalize them to all of Kenya or present them as validated loss or outage estimates.

## Technology and data

The project uses Python for data processing and geospatial analysis; Earth Engine and satellite/climate sources for selected observations; PostgreSQL/PostGIS for spatial storage and queries; and React with the ArcGIS Maps SDK for interactive map and evidence views. The vulnerability workflow also produces GIS outputs in Parquet and GeoJSON.

See the [data catalog](osea_data_pipe/docs/DATA_CATALOG.md) for source families, resolution and implementation notes. A dataset's presence in the catalog does not mean it has a successful, current run or complete coverage.

## Limits and responsible interpretation

The project does not claim a validated national probability of grid failure, a complete current inventory of Kenyan energy assets, verified electrical connections based on geographic proximity, or confirmed flooding from screening candidates. Do not infer outages, monetary losses or asset condition without appropriate supporting evidence. Check each result's source, date, spatial coverage, run status, assumptions and confidence before using it.

## Documentation

Start with the [OSEAS pipeline README](osea_data_pipe/README.md). It links to the [architecture](osea_data_pipe/docs/ARCHITECTURE.md), [data catalog](osea_data_pipe/docs/DATA_CATALOG.md), [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), [model card](osea_data_pipe/docs/MODEL_CARD.md), [Kano flood/CAT status note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md), [pipeline runbook](osea_data_pipe/docs/END_TO_END_RUNBOOK.md), [API contracts](osea_data_pipe/docs/API_CONTRACTS.md) and [frontend guide](osea_data_pipe/docs/FRONTEND_INTEGRATION_GUIDE.md).
