# OSEAS assessment methods

## Current executable methods

### Population exposure

WorldPop Global2 R2025A constrained 100 m population-count cells are summed by pixel center inside each UNOSAT event footprint. Each event’s overlapping source polygons count a cell once. County/ward summaries clip the source footprint to intersecting administrative geometries and retain valid-raster cell coverage. Output means estimated resident population inside a mapped footprint; it does not measure casualties, displacement, service dependency or confirmed impacts.

### Heat

NASA POWER daily T2M_MAX is acquired over the bounded Kenya extent using the provider’s regional grid. Each daily value is compared with the mean monthly T2M_MAX for the same calendar month across 2001–2020. A configurable threshold yields hot-day counts and a nearest-grid-cell (within 45 km) asset exposure screen. Results are gridded near-surface air temperature and monthly-baseline anomalies. They are not land-surface temperature, asset microclimate, equipment damage or outage probabilities. API output is source-version hashed; repeated identical input is deduplicated.

### Fire

NASA FIRMS VIIRS detections are retained as point events with sensor/acquisition metadata and the source confidence category. Optional asset exposure is point-to-asset distance within configured kilometers. The result means proximity to a satellite active-fire detection; it is not a fire perimeter, burned area, confirmed asset impact or proof of no fire. A burned-area product remains separate work.

### Criticality and service dependencies

Only explicitly verified `service_dependencies` relationships count as verified downstream-service context. Candidate relationships remain candidates; asset proximity does not create electrical connectivity. The engine stores source asset attributes and relationship evidence but does not calculate a numeric criticality score without validated topology, served load, redundancy and defensible normalization.

### Vulnerability and resilience

The engine carries measured hazard exposure into asset vulnerability context and records missing sensitivity/adaptive-capacity evidence. It withholds a comprehensive vulnerability score until those inputs exist. Resilience is reported per evidence dimension (hazard exposure, verified alternative supply, topology, outage/restoration and service dependency). Unknown dimensions stay unknown; no composite resilience score is emitted.

### Intervention output

Assets with measured `exposed` records can receive an unranked field-verification/engineering-review candidate. It uses the exposure record IDs as evidence. It does not estimate intervention impact, avoided loss, cost or benefit.

## Idempotency and history

Source-feature IDs and observed source identifiers are stable. Raster-based population assessment IDs incorporate the WorldPop checksum and flood-reference geometry fingerprint. Assessment IDs incorporate canonical input evidence hashes. An identical rerun does not duplicate an output row; changed source content receives a distinct identity. Run rows and source-version rows capture acquisition/processing history. Coverage rows are run-scoped evidence.

## Explicitly outstanding

The current implementation does not produce standalone CHIRPS/ERA5 rainfall anomaly indicators, reusable terrain/drainage/flow-accumulation products, Landsat LST composites, MODIS/Copernicus burned-area outputs, verified feeder topology, scientific criticality/vulnerability/resilience scores, or validated intervention benefits. Kenya-specific precision/recall/IoU requires compatible reference labels and has not been performed.

## Status meanings

- `READY`: executed and persisted with checked outputs.
- `READY_WITH_LIMITATIONS`: executable evidence workflow with known coverage, scale or validation limits.
- `BLOCKED`: a required credential, configured period or external source is missing.
- `NOT_IMPLEMENTED`: no complete acquisition-to-persistence path exists.
- `not_validated` is execution metadata and never means scientific validation.
