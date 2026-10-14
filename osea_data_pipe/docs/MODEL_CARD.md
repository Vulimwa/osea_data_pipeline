# OSEAS model and method card

## Current flood baseline

- **Name/version:** `oseas-s1-relative-backscatter-screen-v2`
- **Task:** bounded event-window flood candidate screening around a caller-provided Kenya-area bounding box.
- **Inputs:** Earth Engine `COPERNICUS/S1_GRD` VV dB images; caller-selected event and baseline dates; one matching `ASCENDING` or `DESCENDING` orbit pass; Copernicus DEM GLO-30 slope; JRC Global Surface Water occurrence; CHIRPS rainfall as context.
- **Processing:** event and baseline VV medians, 20 m focal median, candidate if event VV is below -16 dB and change is below -3 dB, slope below 5°, JRC occurrence below 80%, at least five connected pixels, and vector patch area at least 10,000 m². Thresholds and orbit are CLI parameters and are stored in run provenance. A same-orbit collection must cover >=70% of the ROI in both windows.
- **Output:** polygons labeled `unvalidated_flood_candidate`; `hazard_events.evidence_kind='modeled'`; positive intersecting assets receive `asset_hazard_exposure` rows. Administrative output counts candidates and does not calculate vulnerability or a risk score.
- **Permanent-water handling:** JRC surface-water occurrence is masked. If the configured Kenya lake vector asset is available, mapped lake surfaces are also excluded as permanent water. Rivers are not buffered/masked because genuine floodplain inundation can occur beside a river.
- **Reference evidence:** the Nov 2023 Kenya flood source is stored separately as reference observation evidence for later comparison. Its presence alone is not an independent label validation, and event-level reported area/population are not substituted for geometry-measured areas.
- **Spatial limit:** maximum 1,000 km² per run, 500 output polygons, and 45 days per image window. Larger areas need tiled/export-based processing.
- **Validation:** the supplied November 2023 Kenya reference polygons are now registered and awaiting database ingestion. They were not used to validate existing candidate runs; no precision, recall, IoU, or calibrated confidence is reported.
- **Known limitations:** dark surfaces, wet soil, terrain/shadow effects, vegetation, wind roughening, tidal/inland water changes and differing acquisition conditions can produce omission or commission errors. JRC masks persistent water only through 2021. CHIRPS does not validate inundation. The 30 m DEM is a surface model and slope filter, not hydraulic simulation.
- **Missing-data behavior:** empty S1 windows, insufficient spatial coverage, unavailable DEM/JRC, or invalid periods fail the run; there is no synthetic fallback. Empty candidate output is stored as a completed screening with a quality warning and is not represented as zero risk.

## Prithvi-EO Sen1Floods11 flood segmentation

- **Checkpoint:** `ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11`, pinned to revision `91ce9d38086a80b078a192b374df758b8855b732`.
- **License/task:** Apache-2.0; flood/water segmentation fine-tuned on Sen1Floods11.
- **Input:** Sentinel-2 L1C, six channels in the checkpoint's expected order: Blue, Green, Red, narrow NIR, SWIR1 and SWIR2 (Earth Engine bands B2, B3, B4, B8A, B11 and B12). The pipeline fetches imagery from Earth Engine and invokes the model repository's inference runner; Sentinel-1 SAR is not passed to this optical model. Validity, JRC occurrence and (when configured) mapped-lake masks are auxiliary bands and are not model inputs.
- **Outputs:** class 1 is stored as `water_or_flood_candidate` modeled evidence, then intersected with energy assets and summarized by ward/county. A boundary is marked screened only when the AOI covers it completely; a partially covered unit is recorded as insufficient data. JRC Global Surface Water occurrence >=80% and configured mapped-lake pixels are filtered after inference; missing JRC occurrence is kept with permanence unknown. Outputs are screening candidates and are not proof of an asset failure or flood damage.
- **Run limits:** 5 km² AOI, 45-day image window, bounded scene download, maximum 500 retained polygons. CPU inference is supported but slower.
- **Validation:** real Kenya inference and geospatial validation ran for Garissa processing run `6860135c-5c64-4b9a-bfdb-b9f30a505b93`. It generated five polygons on 2024-04-29, with zero candidate intersections across 11 inventory assets in the pilot AOI. The AOI touches Garissa and Tana River counties and Galbet and Iftin wards; it does not cover any full administrative unit. No independent pixel reference or conventional-baseline comparison was used. The supplied November 2023 reference event is a different date and remains un-ingested, so Kenya precision/recall/IoU remain unevaluated and `validated_for_kenya=false`. See [`PRITHVI_KENYA_VALIDATION.md`](PRITHVI_KENYA_VALIDATION.md).
- **Setup/runtime check:** `npm run oseas:prithvi:setup` downloads and verifies the pinned files, then automatically runs the official sample inference smoke test. The test passed on CPU in this environment. Runtime initializes from the task checkpoint weights and does not fetch the separate foundation checkpoint. This smoke test is not Kenya validation or OSEAS hazard output.
- **Run:** after applying the current schema and completing inventory ingestion, run `npm run oseas:prithvi:flood -- --bbox <west> <south> <east> <north> --event-start YYYY-MM-DD --event-end YYYY-MM-DD`.

The model bundle is downloaded from the [official Hugging Face model repository](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11). Checkpoint availability does not constitute local accuracy validation. Compare against an independent, held-out reference set and the Sentinel-1 threshold baseline before operational use.

This configured checkpoint only produces the flood/water segmentation described above. It is not a burn-scar or land-cover-change checkpoint. Wildfire and environmental-change products need their own task-compatible checkpoint or conventional remote-sensing baseline, plus Kenya-specific validation; this pipeline does not label those hazards from the flood output.

## Other indicators

Heat stress, wildfire exposure, vulnerability, infrastructure criticality, service reliability and grid resilience are **not assessed** by this implementation. Source registry entries do not constitute a model or score.
