# CGF-ACI: standalone Google Earth Engine demo

## Relationship to OSEAS

CGF-ACI (Cascade Grid Failure and Asset Criticality Index) is a separate Google Earth Engine (GEE) analysis and demo. The GEE processing has been completed and its four output assets are hosted in Earth Engine. Integrating those results as a processing stage in the OSEAS data pipeline is future work. The calculations do not currently run through the OSEAS orchestrator, create OSEAS assessment/run records, or replace the production OSEAS vulnerability or resilience assessment.

The hosted outputs can be displayed as map layers by the separate GEE tile-map integration. That is visualization access only: it does not ingest the CGF-ACI outputs into PostGIS, make the tile service an analytical query service, or make the index a validated risk model.

This note describes the CGF-ACI GEE code supplied for the demo. For OSEAS production processing, see [assessment methods](osea_data_pipe/docs/ASSESSMENT_METHODS.md), the [data catalog](osea_data_pipe/docs/DATA_CATALOG.md), and the [flood model card](osea_data_pipe/docs/MODEL_CARD.md). The proposed event-impact extension is described in the [scenario/CAT note](osea_data_pipe/docs/SCENARIO_CAT_MODEL.md).

## Data assets used by the GEE script

### FeatureCollection inputs

| Asset | GEE asset ID | Use in the supplied script |
| --- | --- | --- |
| Power stations | `projects/osea-hack/assets/osea/power-stations` | Loaded and available for display; not passed to the vulnerability calculation. |
| Primary substations | `projects/osea-hack/assets/osea/primary-substations` | Scored; these scores are also aggregated to wards. |
| Distribution transformers | `projects/osea-hack/assets/osea/distribution-transformer` | Loaded for display; not scored by this script. |
| 220 kV lines | `projects/osea-hack/assets/osea/transmission-lines-220kv` | Styled map context only. |
| 132 kV lines | `projects/osea-hack/assets/osea/transmission-lines-132kv` | Styled map context only. |
| 66 kV lines | `projects/osea-hack/assets/osea/transmission-lines-66kv` | Styled map context only. |
| 33 kV lines | `projects/osea-hack/assets/osea/transmission-lines-33kv` | Styled map context only. |
| Existing mini-grids | `projects/osea-hack/assets/osea/existing-mini-grids` | Scored and styled. |
| Mini-grids under development | `projects/osea-hack/assets/osea/mini-grids-under-development` | Styled map context only; not scored. |
| Health facilities | `projects/osea-hack/assets/osea/healthcare-facilities` | Loaded as context; no service-dependency calculation. |
| Schools | `projects/osea-hack/assets/osea/schools` | Loaded as context; no service-dependency calculation. |
| Kenya wards | `projects/osea-hack/assets/osea/kenya_wards` | Defines the analysis bounds and ward summary features. |

### ImageCollection inputs

| Source | GEE collection and band | Supplied computation | Nominal grid |
| --- | --- | --- | --- |
| CHIRPS daily rainfall | `UCSB-CHG/CHIRPS/DAILY`, `precipitation` | 95th percentile of daily precipitation over 2025, per pixel. This is a rainfall-extreme proxy, not flood extent or depth. | About 0.05° (approximately 5.6 km). |
| ERA5-Land daily aggregates | `ECMWF/ERA5_LAND/DAILY_AGGR`, `temperature_2m_max` | Maximum daily 2 m air temperature over 2025, then Kelvin converted to Celsius. | About 0.1° (approximately 11 km). |

These metre values are nominal approximations; inspect the Earth Engine image projection for the exact grid. Neither input is asset-scale climate data.

## Formulas in the supplied script

For location \(x\), let \(P_d(x)\) be a CHIRPS daily precipitation value and \(T_d(x)\) the ERA5-Land daily maximum temperature in Kelvin. The script filters dates from `2025-01-01` to `2026-01-01`; the end date is exclusive, so this selects the full 2025 calendar year.

```text
F(x) = percentile_95({P_d(x) : dates in 2025})
T(x) = max({T_d(x) : dates in 2025}) - 273.15
```

For each surface independently, min and max values are estimated over the geometry of Kenya wards using `reduceRegion(minMax)` at a requested scale of 5,000 m, with `bestEffort: true`:

```text
F_norm(x) = (F(x) - F_min) / (F_max - F_min)
T_norm(x) = (T(x) - T_min) / (T_max - T_min)
H(x) = 0.6 * F_norm(x) + 0.4 * T_norm(x)
```

The script defines the analysis boundary as `kenya_wards.geometry().bounds()`, the rectangular bounding box of the ward collection. Its min/max statistics are therefore computed over that rectangle, not strictly over the union of ward polygons. The 60/40 weights are design assumptions. `H` is a dimensionless, area-relative combination of rainfall and heat indicators; it is not a calibrated hazard probability, flood depth, return-period estimate, or expected damage.

The script fills masked locations in the composite used for asset sampling with a 15 km circular focal mean:

```text
H_sample(x) = H(x), where H is valid
              focal_mean(H, radius = 15 km), where H is masked
```

This is a gap-filling/smoothing operation on masked locations, not additional observation data and not a hydraulic flood model.

For each primary substation and existing mini-grid, the script requests the mean sampled value over its feature geometry at `scale: 1000`, `bestEffort: true`, and `tileScale: 4`:

```text
hazard_exposure(asset) = mean(H_sample over asset geometry)
vulnerability_score(asset) = hazard_exposure(asset) * criticality_weight(asset)
```

Weights actually passed to the scoring function are `0.85` for substations and `0.50` for existing mini-grids. Power stations, transformers and transmission lines are loaded but not scored. The script substitutes a score of zero when the asset reduction returns a null value. That zero can mean no valid sampled pixel; it is not evidence of zero hazard or resilience and should be interpreted with coverage information.

For each ward, the script calculates the mean score of intersecting **substations only**, and records the substation count:

```text
grid_vuln(ward) = mean(vulnerability_score of intersecting substations)
sub_count(ward) = number of intersecting substations
```

When `sub_count` is zero, the script writes `grid_vuln = 0`. That is an empty denominator, not an assessed zero-vulnerability result. The output properties use the short names `grid_vuln`, `sub_count`, and `haz_prof`; the first was shortened to fit Shapefile field-name constraints.

There is no graph of electrical connections in these calculations. The “cascade” in the index name is not modeled: the script does not simulate propagation through a grid, service interruption, failure probability, or outage.

## Resolution and resampling

| Operation | Requested scale / grid | Interpretation |
| --- | --- | --- |
| Min/max statistics | 5,000 m; `bestEffort: true` | Scale requested for the normalization statistics, not a change to source resolution. |
| Asset sampling | 1,000 m; `bestEffort: true` | Scale requested for the geometry reducer. It does not create 1 km or 1 km² independent climate measurements from 5.6 km CHIRPS and 11 km ERA5-Land inputs. |
| Output image | 1,000 m; `EPSG:4326` | Exported pixel grid requested by `Export.image.toAsset`. It is a display/output grid, not a downscaled climate product. |
| Masked-pixel fallback | 15 km circular focal mean | Explicit neighborhood averaging used only for the asset-sampling image where the composite is masked. |

The GEE script does not request a named resampler such as bilinear or bicubic. Where Earth Engine must reproject an image, its default is nearest-neighbour sampling. The explicit focal mean above is the exception for filling masked values. Neither nearest-neighbour reprojection nor exporting at 1,000 m increases the native information content. Always state source pixel size, requested analysis scale, output grid, and any resampling or smoothing separately.

For any future combined raster analysis, choose and record a common CRS, grid alignment, pixel size and nodata policy. Use a categorical-safe method for classes/masks and document a suitable continuous-data resampler for numeric surfaces. Do not mix values across units or periods without an explicit method.

## Hosted outputs and styling

The GEE script checks whether each destination asset exists and skips an existing output rather than deleting or replacing it. It defines four independent Earth Engine asset exports:

| Output | Asset ID | Type and display |
| --- | --- | --- |
| Multi-Hazard Overlay Index | `projects/osea-hack/assets/composite_hazard_raster` | Image exported at requested 1,000 m in EPSG:4326. Display palette `001133`, `0055aa`, `ffee00`, `ff3300`, range 0–0.7; map integration uses opacity 0.65. |
| Wards Grid Resilience Assessment Map | `projects/osea-hack/assets/kenya_wards_vulnerability_vector` | Ward FeatureCollection. `grid_vuln > 0.4`: `#b71c1c44`; `> 0.1`: `#f57f1744`; otherwise `#1b5e2044`; white outline, width 0.5. |
| Substations Risk Profile | `projects/osea-hack/assets/vulnerable_substations_vector` | Substation FeatureCollection. `vulnerability_score > 0.6`: red `#ff1744`; `> 0.3`: yellow `#ffea00`; otherwise green `#00e676`; point size 6. |
| Vulnerable Mini-Grids | `projects/osea-hack/assets/vulnerable_minigrids_vector` | Existing mini-grid FeatureCollection; the script includes an asset export. Map styling is cyan `#00e5ff`, point size 5. |

Other displayed network styles in the GEE script: 220 kV `#e65100` width 3; 132 kV `#ffb74d` width 2; 66 kV `#ba68c8` width 1.5; and 33 kV `#4fc3f7` width 1. Existing mini-grids use cyan; mini-grids under development use `#aa00ff`, point size 4.

The thresholds and colors communicate classes chosen for display; they are not scientifically validated risk categories. The supplied GEE script sets its Code Editor basemap to `SATELLITE`. That is independent of the OSEAS web application's basemap setting. The script creates ward summaries only, not county summaries or a county/ward scale handover.

## What this does and does not provide

CGF-ACI is useful as a visual demonstration of overlaying selected climate indicators with energy assets. It is not part of the OSEAS pipeline and does not produce pipeline assessment records. It does not estimate damage ratios, money lost, customers affected, service dependencies, avoided outages, or asset failure likelihood. A 100 m or 1 km request must never be presented as finer climate resolution than the input datasets.

The four outputs and their GEE asset IDs are listed above. A future OSEAS integration should record the GEE script revision, source asset versions, date range, reducer scales, assumptions and export task status in OSEAS provenance; those values are not currently OSEAS pipeline-run metadata.
