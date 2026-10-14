# OSEAS assessment methods

## Current executable methods

### Population exposure

WorldPop Global2 R2025A constrained 100 m population-count cells are summed by pixel center inside each UNOSAT event footprint. Each event’s overlapping source polygons count a cell once. County/ward summaries clip the source footprint to intersecting administrative geometries and retain valid-raster cell coverage. Output means estimated resident population inside a mapped footprint; it does not measure casualties, displacement, service dependency or confirmed impacts.

### Heat

NASA POWER daily T2M_MAX is acquired over the bounded Kenya extent using the provider’s regional grid. Each daily value is compared with the mean monthly T2M_MAX for the same calendar month across 2001–2020. A configurable threshold yields hot-day counts and a nearest-grid-cell (within 45 km) asset exposure screen. Results are gridded near-surface air temperature and monthly-baseline anomalies. They are not land-surface temperature, asset microclimate, equipment damage or outage probabilities. API output is source-version hashed; repeated identical input is deduplicated.

### Fire

NASA FIRMS VIIRS detections are retained as point events with sensor/acquisition metadata and the source confidence category. Latest-day NRT results are requested inside the Kenya county-boundary envelope and then clipped to the exact boundary union; optional historical date pairs use the same AOI. Optional asset exposure is point-to-asset distance within configured kilometers. The result means proximity to a satellite active-fire detection; it is not a fire perimeter, burned area, confirmed asset impact or proof of no fire. A burned-area product remains separate work.

### Nighttime lights and human-activity context

NASA VIIRS Black Marble VNP46A2 daily radiance is read from the public Earth Engine catalog. The adapter masks to `Mandatory_Quality_Flag == 0` (high-quality persistent lights), computes the monthly median from available daily images, and summarizes 36 complete recent months against a separately recorded January 2012-December 2015 baseline. January 2012 is partial because the collection begins on January 19. Percent change is calculated only when the baseline median is nonzero. Missing/invalid months do not become zero; valid-month coverage and valid pixel counts accompany the estimate. A mapped zero is retained only when the explicit valid-observation band shows at least one valid contributor. Counties/wards use polygon zonal statistics. Energy assets and critical services use a documented 500 m buffer around a representative point to contextualize nearby lights. The data are not electricity access, feeder linkage, outage duration, energy use, or proof of damage. Source image counts and selected dates are stored in provenance. NASA's file product defines a 0.1 scale factor; Earth Engine catalog values are already exposed in the documented radiance unit and are not scaled a second time. [NASA VNP46A2 filespec](https://ladsweb.modaps.eosdis.nasa.gov/filespec/VIIRS/2/VNP46A2_v2.0.fs), [Earth Engine catalog](https://developers.google.com/earth-engine/datasets/catalog/NASA_VIIRS_002_VNP46A2)

### Criticality and service dependencies

Only explicitly verified `service_dependencies` relationships count as verified downstream-service context. Candidate relationships remain candidates; asset proximity does not create electrical connectivity. The engine stores source asset attributes and relationship evidence but does not calculate a numeric criticality score without validated topology, served load, redundancy and defensible normalization.

### Vulnerability and resilience

The engine carries measured hazard exposure into asset vulnerability context and records missing sensitivity/adaptive-capacity evidence. It withholds a comprehensive vulnerability score until those inputs exist. Resilience is reported per evidence dimension (hazard exposure, verified alternative supply, topology, outage/restoration and service dependency). Unknown dimensions stay unknown; no composite resilience score is emitted.

The same run writes a current ward and county summary and exposes it through `vulnerability_summaries` and the administrative-summary endpoint. It includes the number of assigned assets, per-asset type counts, observed hazard-exposure denominators, hazard-specific counts, and the number of composite scores withheld. `systemClassCounts` separates known centralized network classes and decentralized mini-grids, with distribution assets, generation assets, and unclassified asset types kept distinct. This is an inventory-class grouping, not a finding about feeder connectivity or islanding. A summary is `partial` when measured exposure evidence exists, `unknown` when assets exist but no measured exposure is available, and `not_assessed` when no assets are assigned. These are screening summaries, not validated vulnerability scores.

### Intervention output

Assets with measured `exposed` records can receive an unranked field-verification/engineering-review candidate. It uses the exposure record IDs as evidence. It does not estimate intervention impact, avoided loss, cost or benefit.

## Idempotency and history

Source-feature IDs and observed source identifiers are stable. Raster-based population assessment IDs incorporate the WorldPop checksum and flood-reference geometry fingerprint. Assessment IDs incorporate canonical input evidence hashes. An identical rerun does not duplicate an output row; changed source content receives a distinct identity. Run rows and source-version rows capture acquisition/processing history. Coverage rows are run-scoped evidence.

## Explicitly outstanding

The current implementation does not produce standalone CHIRPS/ERA5 rainfall anomaly indicators, reusable terrain/drainage/flow-accumulation products, Landsat LST composites, MODIS/Copernicus burned-area outputs, verified feeder topology, scientific criticality/vulnerability/resilience scores, or validated intervention benefits. Black Marble now uses the configured Earth Engine account and the 36-month interval in `.env`; its live national acquisition and persisted row count are reported in implementation status after the run. Kenya-specific precision/recall/IoU requires compatible reference labels and has not been performed.

## Status meanings

- `READY`: executed and persisted with checked outputs.
- `READY_WITH_LIMITATIONS`: executable evidence workflow with known coverage, scale or validation limits.
- `BLOCKED`: a required credential, configured period or external source is missing.
- `NOT_IMPLEMENTED`: no complete acquisition-to-persistence path exists.
- `not_validated` is execution metadata and never means scientific validation.
