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

For event \(e\), reporting unit \(u\), and daily precipitation \(p_d\):

```text
event_total(e,u) = sum(p_d) over the 30-day event window
baseline_mean(e,u) = mean(yearly 30-day totals for the same calendar window, 2001–2020)
anomaly_mm(e,u) = event_total(e,u) - baseline_mean(e,u)
anomaly_percent(e,u) = 100 * anomaly_mm / baseline_mean, when baseline_mean > 0
```

At least 90% of the 30 daily images are required; the reducer requests 5,566 m scale. Baseline coverage can vary by unit and is recorded. This is rainfall context, not flood depth.

### NASA POWER heat context

The heat adapter uses daily maximum 2 m air temperature (`T2M_MAX`), compares each day with the mean for the corresponding calendar month over 2001–2020, and can count days above a configured threshold. Asset context uses the nearest provider grid cell within the configured search distance. NASA POWER is coarse gridded near-surface air temperature, not land-surface temperature, equipment temperature, damage or outage probability.

For daily value \(x_d\), month \(m(d)\), monthly baseline mean \(B_m\), and configured threshold \(q\):

```text
heat_anomaly(d) = x_d - B_m(d)
hot_days = count(valid days where x_d >= q)
```

The processor also records the maximum daily T2M_MAX and valid-day fraction per provider grid cell. Asset matching uses the nearest cell within 45 km; it does not interpolate to asset-scale temperature.

### VIIRS nighttime radiance

The Black Marble adapter screens daily VNP46A2 imagery using its quality flag, creates monthly medians, and compares a selected recent period with a baseline period. It records valid observations so a true zero can be distinguished from missing or invalid data. Administrative values use polygon summaries; asset and service context uses a documented buffer. Radiance is a human-activity context signal, not proof of electricity access, feeder connection, outage or damage.

The adapter and persistence workflow exist, but the latest accepted data state must be confirmed from the live run records. Do not rely on an old local log as evidence of a completed run.

The quality rule is `Mandatory_Quality_Flag == 0`. For each zone, valid monthly radiance values are summarized with a median for the selected recent and baseline periods:

```text
change_percent = 100 * (recent_median - baseline_median) / abs(baseline_median)
valid_month_fraction = valid_month_count / requested_month_count
```

`change_percent` is null if either period lacks a value or the baseline median is zero. The monthly raster is retained on a 15-arc-second grid (about 500 m); zonal extraction does not upsample it.

### FIRMS active-fire detections

The adapter requests NASA FIRMS active-fire detections for the selected sensor/date window, clips the results to Kenya administrative coverage, and can measure proximity to assets. A detection is not a fire perimeter, burned area or confirmed impact. Zero detections do not prove that no fire occurred.

### WorldPop population exposure

The WorldPop workflow sums valid population-count cells whose centers fall within a flood-reference footprint. It can also summarize intersections with county and ward boundaries. Provenance includes the source raster checksum, reference year and valid-raster coverage. Values are estimated residents in the footprint, not confirmed affected people, displacement, or population served by a particular energy asset.

For the selected footprint \(g\), the calculation is:

```text
population_estimate(g) = sum(population_count_i) over valid cells whose centers fall in g
valid_cell_fraction(g) = valid included cells / all raster cells whose centers fall in g
```

The population cells are not resampled by this zonal calculation. Event polygons are combined so overlapping polygons do not count the same cell twice within that event.

### Sentinel-1 flood screening

The bounded Sentinel-1 workflow compares event-window VV backscatter with a same-orbit baseline, applies terrain and persistent-water screens, then extracts connected candidate areas and measures positive intersections with inventory assets. Output is modeled flood-candidate evidence. It has not been calibrated as a flood probability or validated nationally against independent reference labels.

The principal screening quantities and default candidate rule are:

```text
event_vv = focal_median(median(event VV images), radius = 20 m)
baseline_vv = focal_median(median(baseline VV images), radius = 20 m)
drop = event_vv - baseline_vv
candidate =
  event_vv < -16 dB
  AND drop < -3 dB
  AND slope < 5 degrees
  AND JRC water occurrence < 80%
  AND not in a supplied mapped-lake mask (when present)
```

Defaults are configurable. Connected candidate patches are retained when they have at least five connected pixels and pass the configured minimum polygon area (default 10,000 m²); vectorization requests a 20 m scale. These are thresholds for candidate screening, not a calibrated flood probability.

### Prithvi flood/water segmentation

The configured Prithvi-EO Sen1Floods11 checkpoint classifies Sentinel-2 optical input into water/flood candidate pixels. The pipeline applies validity and persistent-water masks, then stores candidate geometries or administrative pixel summaries depending on the run mode. Kenya-specific accuracy has not been established; see [`MODEL_CARD.md`](MODEL_CARD.md).

For nationwide administrative summaries, the retained measurements are counts, not continuous flood depth:

```text
valid_coverage = valid_pixels / total_pixels
candidate_area_m2 = candidate_pixels * (10 m * 10 m)
```

Candidate pixels are class-1 model outputs after the validity and persistent-water rules; they are not confirmed inundation. Administrative geometries are rasterized to the 10 m summary grid for pixel counting.

## Exposure, vulnerability, criticality and resilience

Exposure is recorded when the implemented spatial method finds a positive relationship between an asset and hazard evidence. Its meaning depends on the hazard geometry, observation period, spatial coverage and processing method.

Production OSEAS assessments do not currently infer a general numeric vulnerability, criticality or resilience score when required evidence is missing. Relevant gaps include asset condition/sensitivity, served load, validated network topology, redundancy, outage/restoration history and verified service dependencies. Such dimensions remain unknown or withheld.

County and ward summaries report inventory and evidence counts, denominators, status and provenance where available. They are screening summaries, not validated composite risk scores. An asset's proximity to a service does not establish that it supplies that service.

Measured exposure may support an unranked recommendation for field verification or engineering review. OSEAS does not calculate intervention effectiveness, avoided losses, cost-effectiveness or benefit without supporting methods and data.

## Standalone GEE CGF-ACI demo

CGF-ACI is a separate Earth Engine demo that has been processed and exported to four hosted GEE assets; it is **not yet an OSEAS pipeline stage**. Its layers can be displayed through the separate GEE tile-map integration, but its scoring is not run by the OSEAS orchestrator or stored as OSEAS production assessments. The supplied current script uses CHIRPS daily 95th-percentile rainfall and ERA5-Land daily maximum 2 m temperature in 2025; it normalizes both over the ward collection's rectangular bounds; combines them with assumed weights of 0.6 and 0.4; fills masked sampling locations with a 15 km focal mean; samples at a requested 1,000 m scale; applies weights of 0.85 to substations and 0.50 to existing mini-grids; and reports ward means from intersecting substations only. Integrating it into OSEAS with pipeline run and provenance records is a future step. The actual formulas, four hosted outputs, all GEE input assets, and the export/display settings are documented in [`../../CGF_ACI.md`](../../CGF_ACI.md).

The `1,000 m` output raster scale and asset sampling scale do not change the approximately 5.6 km CHIRPS or 11 km ERA5-Land source resolutions. The code does not request a named resampler; Earth Engine uses nearest-neighbour sampling when reprojection is required. The explicit 15 km focal mean fills masked pixels for asset sampling and is not new observed data. Null asset samples and wards with no assessed substations are written as zero by the script, so those cases must be treated as missing/unknown, not as evidence of no hazard. The index contains no electrical network topology or outage history and does not predict cascade failures. See the detailed [CGF-ACI GEE note](../../CGF_ACI.md) for all inputs, outputs, formulas, styles and limitations.

## Outstanding methods

The repository does not provide validated national estimates of asset failure probability, outage duration, electrical cascade propagation, feeder-level reliability, or intervention benefit. Broad ERA5 climate indicators, Landsat land-surface temperature, burned-area exposure, future-climate projections and comprehensive raster zonal summaries require additional source-specific implementation and validation.

The proposed scenario/CAT extension is documented separately in [`SCENARIO_CAT_MODEL.md`](SCENARIO_CAT_MODEL.md). It describes future hazard-intensity and damage-function work; it is not part of the implemented screening calculations above. Source resolutions and documented resampling choices are summarized in [`DATA_CATALOG.md`](DATA_CATALOG.md).
