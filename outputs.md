A. National energy and contextual data foundation
What exists, where it exists, and what surrounds it.
- Energy-asset inventory: power stations, substations, transformers, transmission lines, mini-grids and other verified assets.
- Network geometry and connectivity, where available.
- Counties, wards, settlements, buildings, roads, rivers and water bodies.
- Population distribution and density.
- Night-time lights and changes in human activity.
- Land cover, vegetation, terrain, soil and drainage context.
- Critical services: healthcare, water, schools and other available facilities.
- Source catalog, data coverage, dates and provenance.


B. Climate and hazard intelligence
What hazards occur, where, and relative to what baseline.
- Flood candidate extents and reference-event footprints.
- Rainfall accumulations, anomalies and extreme-rainfall indicators.
- Flood susceptibility context from terrain, drainage and hydrology.
- Heat exposure, land-surface temperature and heat anomalies.
- Wildfire detections, burned areas and fire proximity.
- Drought or water-stress indicators where supported.
- Severe-wind hazard indicators only where appropriate hazard data exists.
- Hazard observation coverage, dates, thresholds and quality flags.

C. Asset exposure and consequences
Which infrastructure intersects the evidence, and what may be affected.
- Asset-by-hazard exposure register.
- Exposed transmission-line length and percentage of assessed length.
- Exposed substations, transformers, power stations and mini-grids.
- Estimated population within hazard footprints.
- Contextual night-time-light intensity around exposed infrastructure.
- Critical facilities and verified service dependencies.
- Asset criticality and vulnerability screening, with explanations.
- Resilience indicators and explicit unknowns.

D. National-to-local reporting
Where evidence is concentrated, incomplete or requires investigation.
- National overview and county/ward summaries.
- Asset counts, assessed counts and exposure statistics.
- Hazard intensity and observation coverage.
- Population potentially exposed.
- Critical infrastructure and service-context summaries.
- Data gaps and unassessed locations.
- Time-series and event comparisons.


E. Decision support
What should be investigated or prioritized, and why.
- Transparent intervention-priority register.
- Asset and location rankings with supporting evidence.
- Candidate hardening, protection or alternative-siting scenarios.
- Baseline-versus-scenario comparisons.
- Evidence-based service-impact context.
- Sensitivity analysis and explanations of ranking changes.
- Recommended data collection and field-verification priorities.

F. Operational and frontend outputs
The infrastructure that makes the product usable.
- Versioned, map-ready layers and filtered GeoJSON APIs.
- Asset detail, hazard assessment and administrative-summary endpoints.
- Source catalog and data-coverage endpoints.
- Scenario, intervention and run-history APIs.
- Provenance, data-quality and model-validation records.
- Processing status, error logs, warnings and readiness checks.

G. OSEAS evidence-to-action product requirements
The platform must connect hazard evidence to infrastructure and service decisions, with traceability and explicit unknowns. A generic national asset catalogue or a set of hazard maps is not the deliverable.
- Centralized and decentralized energy assets assessed separately by asset class and source completeness.
- Per-asset evidence chain from source, observation date, method, spatial coverage, and processing run through measured exposure and decision-support context.
- Reliability-risk context that distinguishes observed hazard exposure from actual outage, failure, or service interruption. Outage history and verified network topology are required before estimating those outcomes.
- Verified service relationships and documented unknowns; geographic proximity alone is not an electrical dependency.
- Population and human-activity context linked to exposed infrastructure without claiming that a specific asset serves a settlement.
- County, ward, network, and asset summaries with assessed/unknown denominators and valid observation coverage.
- Intervention investigation priorities whose evidence contributions are visible; unsupported engineering benefit and cost claims remain unavailable.

H. First-class NASA VIIRS Black Marble nighttime lights
Nighttime lights are a contextual evidence dataset and map layer, not a basemap decoration or an electricity-access proxy.
- Use NASA Black Marble monthly VNP46A3 and, where useful, annual VNP46A4 radiance composites with product quality flags.
- Track valid observations, quality-mask exclusions, source dates, radiance units, resolution, source version, and spatial coverage.
- Produce quality-aware recent-period radiance and an explicitly selected earlier baseline, plus change indicators for administrative areas, energy assets, and critical services where coverage supports them.
- Distinguish true zero radiance from missing, invalid, cloud-affected, or low-quality observations.
- Treat changes as investigation signals only. Night lights do not prove household electricity access, feeder/substation service, outage duration, asset damage, or causal impact.
- Do not finalize the “latest 36 complete months” until the source manifest confirms that the months and Kenya tiles are actually available; retain the selected dates in run provenance.
