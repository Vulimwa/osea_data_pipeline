# Prithvi Kenya flood-screen pilot

Run date: 2026-10-14. This report records the first real Kenya scene processed with the pinned Prithvi-EO-2.0 Sen1Floods11 task checkpoint. The output is a screening layer, not a verified flood map.

## Validation status

This April 2024 pilot did not use the separately supplied November 2023 Kenya flood reference polygons. Those polygons are now registered and awaiting ingestion; temporal mismatch means they cannot directly validate this scene without additional event/date evidence.

| Gate | Status | Evidence |
|---|---|---|
| Inference executed | **PASS — INFERENCE_EXECUTED** | Official task inference ran on the selected Garissa-area Sentinel-2 L1C image. The exact model, revision, scene ID and parameters are in the run metadata. |
| Geospatial output checked | **PASS — OUTPUT_GEOSPATIAL_VALIDATED** | The one-band class raster is 112×134 at 10 m in EPSG:32737. Its dimensions, CRS and affine transform match the source grid. Class values were normalized from the official inference writer’s byte encoding and checked against the valid-pixel mask. Five candidate geometries passed the PostGIS validity check. |
| Kenya accuracy evaluated | **NOT EVALUATED — SCIENTIFICALLY_VALIDATED** | No independent pixel-level reference labels were compared with the prediction. Precision, recall and IoU are not available. Do not present this result as scientifically validated. |

## Pilot and source scene

- **AOI:** `39.632,-0.457,39.642,-0.445` (west,south,east,north), approximately 1.48 km²; this is a small pilot near Garissa Town, not a county-wide analysis.
- **Scene:** `COPERNICUS/S2_HARMONIZED/20240429T072621_20240429T074427_T37MEV`, acquired `2024-04-29T07:50:08Z`; scene-wide `CLOUDY_PIXEL_PERCENTAGE` was 23.27%.
- **AOI valid-pixel coverage:** 99.47% after masking QA60 opaque cloud and cirrus bits. QA60 does not remove cloud shadows.
- **Inputs:** L1C B2, B3, B4, B8A, B11, B12 in the checkpoint order (blue, green, red, narrow NIR, SWIR1, SWIR2). Earth Engine documents Sentinel-2 L1C bands as UINT16 TOA reflectance scaled by 10,000; the official task inference rescales and normalizes the selected channels. [Earth Engine S2 L1C catalog](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_HARMONIZED)
- **Checkpoint:** `ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11`, revision `91ce9d38086a80b078a192b374df758b8855b732`. This is the Sentinel-2 flood segmentation task checkpoint, not a general Prithvi model. [Official task model card](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11)

## Results

- Valid pixels: 15,008; class 0 background: 12,011; class 1 water/flood candidates: 2,997; cloud/no-data pixels: 0.
- Five connected candidate polygons remained after the 10,000 m² minimum-patch filter. Their summed mapped area is about **0.287 km²**.
- JRC Global Surface Water occurrence >=80% was excluded as persistent water. Missing JRC occurrence is retained with permanence unknown; most class-1 pixels had no JRC occurrence value in this export. This makes the layer conservative about known permanent water while retaining uncertainty in the candidate polygons.
- **Asset overlay:** 11 energy assets are within the AOI (9 distribution transformers, 1 existing mini-grid, 1 primary substation). None intersects a candidate polygon. Their local GeoJSON status is `unknown`, not `not_exposed`; no polygon intersection does not establish safety or absence of flood risk.
- **Administrative overlay:** the AOI touches Garissa and Tana River counties and Galbet and Iftin wards. Four partial summaries were stored; none of those administrative units is fully covered, so every summary is `insufficient_data`. Counts refer only to the pilot AOI portion.
- A UNOSAT product documents cumulative NOAA-VIIRS satellite-detected water in Kenya for 24–28 April 2024 and reports county-scale context including Garissa. This is useful event context, but its date window, footprint and scale do not provide aligned 10 m labels for this 29 April AOI. It was not used to calculate accuracy metrics. [UNOSAT Kenya product 3828](https://unosat.org/products/3828)

## Persisted run and artifacts

- Processing run: `6860135c-5c64-4b9a-bfdb-b9f30a505b93`
- Model run: `318236af-31e1-44b6-acfd-127df69e6c4f`
- Database status: `completed`; one hazard event, one flood extent, zero positive asset-exposure rows, four administrative summaries. A read-only post-run audit found one event for this fingerprint and no duplicate exposure rows.
- API: `GET /api/v1/oseas/layers/flood_candidate/geojson` returns the completed candidate polygons and run provenance.
- Files (relative to the backend directory):
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/sentinel2_l1c.tif` — downloaded eight-band source package, including validity and JRC helper bands.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/prithvi_class_labels.tif` — normalized, georeferenced class raster; nodata is 255.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/flood_candidates.geojson` — five candidate polygons in EPSG:4326.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/asset_exposures.geojson` — all 11 assets with intersection status and provenance.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/administrative_summary.geojson` — partial county/ward summaries.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/preview.png` — RGB scene with candidate overlay.
  - `outputs/prithvi/6860135c-5c64-4b9a-bfdb-b9f30a505b93/run_metadata.json` — parameters, source details, raster checks and validation flags.

## Nairobi/Kiambu reference-window run (2026-10-15)

- **Processing run:** `49910391-e43b-4bf6-8cd9-fadc737ce709`; **model run:** `9df5e311-ad20-4386-8f42-54c6d2832222`.
- **AOI:** `37.0588,-1.2335,37.0788,-1.2135` (west,south,east,north), approximately 4.92 km2; event window 2024-04-29 through 2024-05-04.
- **Scene:** `COPERNICUS/S2_HARMONIZED/20240502T073621_20240502T075440_T37MBU`, acquired `2024-05-02T08:00:28Z`. Scene-wide cloud was 62.9%; QA60 masking left 99.58% valid pixels in this AOI.
- **Output:** official pinned inference completed in 205 seconds. It classified 4,504 valid pixels as water/flood candidates and generated 3 connected polygons, stored as one unioned MultiPolygon hazard event. The class raster has 168 no-data pixels.
- **Asset/admin overlay:** zero energy assets are inside this AOI, so it produced no asset intersection rows. Four county/ward units were touched; none is fully covered, and their summaries remain partial/insufficient. This is a localized reference-window example, not a national map.
- **Validation:** inference and geospatial grid checks passed; Kenya accuracy remains **NOT EVALUATED**. No precision, recall, or IoU is claimed. The output is not a confirmed flood footprint.
- **Files:** `outputs/prithvi/49910391-e43b-4bf6-8cd9-fadc737ce709/` contains `sentinel2_l1c.tif`, `prithvi_class_labels.tif`, `flood_candidates.geojson`, `asset_exposures.geojson`, `administrative_summary.geojson`, `preview.png`, and `run_metadata.json`.

## Reproduction

```powershell
npm run oseas:prithvi:flood -- --bbox 39.632 -0.457 39.642 -0.445 `
  --event-start 2024-04-29 --event-end 2024-04-30 `
  --scene-id 20240429T072621_20240429T074427_T37MEV --max-cloud-percent 30
```

Inference used CPU and took about 5.6 minutes including scene download and database writes. Re-running uses deterministic hazard-event and exposure identifiers for this source and parameter fingerprint; model/processing run records remain separate provenance records.

## What is still required for scientific validation

Obtain a local reference flood footprint aligned to the AOI and acquisition date, document its resolution and interpretation, and compare both this model and a conventional Sentinel-2/SAR baseline on held-out pixels. Report precision, recall, IoU, and results by landscape/asset context. Until that evaluation is complete, use the five polygons only as candidate evidence for review.
