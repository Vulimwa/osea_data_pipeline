# Model card: flood screening

OSEAS contains two flood/water candidate workflows. Both are screening tools. Neither is currently a validated national flood map, calibrated probability of inundation, or estimate of asset damage.

## Sentinel-1 relative-backscatter screen

**Purpose:** identify candidate flood-like areas for review in a bounded event and baseline window.

**Inputs:** Earth Engine Sentinel-1 VV backscatter, explicit event and baseline dates, a matching orbit pass, Copernicus DEM slope, JRC Global Surface Water occurrence, and optional mapped lake polygons. CHIRPS rainfall may be stored as event context; it is not the classifier.

**Method:** compare event and baseline VV medians, apply configured backscatter/change thresholds, remove steep terrain and persistent water, and filter connected patches by size. The processor requires same-orbit image coverage of at least 70% in each period.

**Output:** modeled candidate polygons and positive geometric intersections with energy assets. Output records preserve method and run provenance.

**Operational limit:** bounded to at most 1,000 km², 45 days per image window and 500 output polygons per run. Use tiling or a separately designed batch workflow for larger areas.

**Limitations:** radar response can vary with soil moisture, vegetation, terrain, wind, acquisition geometry and surface type. Water masks can be incomplete or stale. A candidate is not confirmed inundation. No Kenya-wide precision, recall, IoU, or calibrated confidence has been established.

## Prithvi-EO Sen1Floods11

**Purpose:** generate water/flood candidate evidence from optical imagery using a task-specific segmentation model.

**Checkpoint:** `ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11`, pinned in the implementation to revision `91ce9d38086a80b078a192b374df758b8855b732`.

**Input:** six Sentinel-2 L1C optical bands in checkpoint order: Blue, Green, Red, narrow NIR, SWIR1 and SWIR2 (B2, B3, B4, B8A, B11 and B12). Validity and persistent-water masks are auxiliary processing inputs, not model channels.

**Output:** class-1 water/flood candidates, followed by spatial exposure intersections and/or county/ward candidate-pixel and coverage summaries. Bounded pilot and nationwide tiled modes persist different output forms; nationwide output is administrative summaries rather than a retained national prediction raster.

**Run limits:** bounded pilots cover at most 5 km² and use an explicit image period. Nationwide processing uses resumable 512×512 chips at 10 m with an overlap so only each non-overlapping core contributes to counts. It may take many hours, particularly on CPU.

**Validation:** a checkpoint setup smoke test confirms the inference package can run on its sample. That is not geographic validation. Kenya-specific independent precision, recall and IoU have not been established. See [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md) for interpretation requirements.

## CGF-ACI is outside the OSEAS pipeline

CGF-ACI is a standalone Google Earth Engine demo that has been processed and exported to hosted assets. It is not an OSEAS processing stage, a Prithvi model or a production score. Its outputs can be visualized through the separate tile-map integration, but the GEE calculation is not orchestrated by OSEAS and its scores are not OSEAS assessment records. Integrating the completed GEE work into the pipeline is future work. The current script combines normalized CHIRPS rainfall and ERA5-Land daily maximum temperature, applies assumed weights to substations and existing mini-grids, and averages assessed substation scores by ward. It does not model electrical cascade propagation, outages, or equipment failure. See the detailed [CGF-ACI GEE note](../../CGF_ACI.md) and [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md).

## Use and reporting

Always report the source period, spatial coverage, run status and candidate status. Do not present an empty result as proof of no flood, a screening candidate as confirmed inundation, or an asset intersection as failure or outage. Check the latest run and data-quality records before using any output.

The Kano Plains interface is a pilot view, not evidence that this repository's flood-screening workflows perform a return-period CAT calculation. The CAT model is implemented in the separate [vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability); see [`SCENARIO_CAT_MODEL.md`](SCENARIO_CAT_MODEL.md) for the distinction from CGF-ACI and this repository's screening outputs.
