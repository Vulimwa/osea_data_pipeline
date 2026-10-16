# Assessment methods

This document describes calculations that have an implemented processing path and separates them from exploratory prototypes and unimplemented indicators. A source appearing in the catalog does not mean that it has been processed. Check the latest run and readiness records before presenting an output as current.

## Evidence terms

- **Observation:** a source measurement such as daily rainfall or air temperature.
- **Hazard candidate:** a location classified by a screening method as potentially affected.
- **Exposure:** a measured spatial relationship between an asset and hazard evidence.
- **Assessment:** an interpretation that depends on stated evidence and assumptions.

An empty query or missing assessment is not a measured zero. Each result should retain its period, source, method, coverage and processing run where the processor provides them.

## Implemented or available processing paths

### CHIRPS rainfall context

The CHIRPS adapter calculates 30-day rainfall totals for dated flood-reference events and compares them with same-calendar 30-day windows from 2001–2020. It persists the total, absolute anomaly and percentage anomaly for county/ward intersections. Percentage anomaly is null if the baseline total is zero. The result describes rainfall context; it is not a mapped flood extent or asset-damage estimate.

### NASA POWER heat context

The heat adapter uses daily maximum 2 m air temperature (`T2M_MAX`), compares each day with the mean for the corresponding calendar month over 2001–2020, and can count days above a configured threshold. Asset context uses the nearest provider grid cell within the configured search distance. NASA POWER is coarse gridded near-surface air temperature, not land-surface temperature, equipment temperature, damage or outage probability.

### VIIRS nighttime radiance

The Black Marble adapter screens daily VNP46A2 imagery using its quality flag, creates monthly medians, and compares a selected recent period with a baseline period. It records valid observations so a true zero can be distinguished from missing or invalid data. Administrative values use polygon summaries; asset and service context uses a documented buffer. Radiance is a human-activity context signal, not proof of electricity access, feeder connection, outage or damage.

The adapter and persistence workflow exist, but the latest accepted data state must be confirmed from the live run records. Do not rely on an old local log as evidence of a completed run.

### FIRMS active-fire detections

The adapter requests NASA FIRMS active-fire detections for the selected sensor/date window, clips the results to Kenya administrative coverage, and can measure proximity to assets. A detection is not a fire perimeter, burned area or confirmed impact. Zero detections do not prove that no fire occurred.

### WorldPop population exposure

The WorldPop workflow sums valid population-count cells whose centers fall within a flood-reference footprint. It can also summarize intersections with county and ward boundaries. Provenance includes the source raster checksum, reference year and valid-raster coverage. Values are estimated residents in the footprint, not confirmed affected people, displacement, or population served by a particular energy asset.

### Sentinel-1 flood screening

The bounded Sentinel-1 workflow compares event-window VV backscatter with a same-orbit baseline, applies terrain and persistent-water screens, then extracts connected candidate areas and measures positive intersections with inventory assets. Output is modeled flood-candidate evidence. It has not been calibrated as a flood probability or validated nationally against independent reference labels.

### Prithvi flood/water segmentation

The configured Prithvi-EO Sen1Floods11 checkpoint classifies Sentinel-2 optical input into water/flood candidate pixels. The pipeline applies validity and persistent-water masks, then stores candidate geometries or administrative pixel summaries depending on the run mode. Kenya-specific accuracy has not been established; see [`MODEL_CARD.md`](MODEL_CARD.md).

## Exposure, vulnerability, criticality and resilience

Exposure is recorded when the implemented spatial method finds a positive relationship between an asset and hazard evidence. Its meaning depends on the hazard geometry, observation period, spatial coverage and processing method.

Production OSEAS assessments do not currently infer a general numeric vulnerability, criticality or resilience score when required evidence is missing. Relevant gaps include asset condition/sensitivity, served load, validated network topology, redundancy, outage/restoration history and verified service dependencies. Such dimensions remain unknown or withheld.

County and ward summaries report inventory and evidence counts, denominators, status and provenance where available. They are screening summaries, not validated composite risk scores. An asset's proximity to a service does not establish that it supplies that service.

Measured exposure may support an unranked recommendation for field verification or engineering review. OSEAS does not calculate intervention effectiveness, avoided losses, cost-effectiveness or benefit without supporting methods and data.

## CGF-ACI prototype

The separate hackathon Earth Engine script defines **Cascade Grid Failure and Asset Criticality Index (CGF-ACI)** as an exploratory screening formula:

1. Reduce 2025 CHIRPS daily precipitation to its 95th percentile and ERA5-Land 2 m temperature to its maximum.
2. Independently min-max normalize both surfaces over the Kenya boundary to 0–1.
3. Form a composite: `0.6 × normalized rainfall + 0.4 × normalized heat`.
4. Sample the composite at assets and multiply by an assumed asset-type factor: 0.95 for power stations, 0.85 for substations, and 0.50 for other types in the supplied script.
5. Average intersecting substation scores within each ward.

The index helps visualize where the selected climate signals and mapped energy assets overlap, compare broad ward patterns, and direct follow-up investigation. It is not a probability of grid failure or an estimate of outages. The weights are assumptions, the model has no electrical topology or failure history, min-max normalization depends on the selected area and outliers, and a ward mean can conceal individual high values. A 100 m sampling request does not increase the native climate resolution. Rainfall intensity is not flood inundation.

## Outstanding methods

The repository does not provide validated national estimates of asset failure probability, outage duration, electrical cascade propagation, feeder-level reliability, or intervention benefit. Broad ERA5 climate indicators, Landsat land-surface temperature, burned-area exposure, future-climate projections and comprehensive raster zonal summaries require additional source-specific implementation and validation.
