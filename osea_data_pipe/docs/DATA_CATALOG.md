# Data catalog

The machine-readable source registry is [`../config/data_catalog.json`](../config/data_catalog.json). It is used by the catalog audit and API. A registry entry records a source considered for OSEAS integration; it does not prove that the source is currently accessible, that an adapter has completed, or that usable output is stored. CGF-ACI has been processed separately in GEE and its outputs are hosted, but it is not yet an OSEAS pipeline stage; its assets are listed here for provenance and separate map visualization.

Before reporting current availability, check the source's latest processing run, quality records and `/api/v1/oseas/readiness`. Avoid preserving transient run counts or process state in this reference document.

## Infrastructure and reference assets

Configured Earth Engine feature-table sources are defined in [`../oseas/config.py`](../oseas/config.py); full asset IDs are provided by backend `GEE_ASSET_*` settings.

| Group | Sources | Use |
| --- | --- | --- |
| Administrative boundaries | Kenya counties and wards | Spatial assignment and county/ward reporting. Verify source IDs, geometry validity and refresh status before treating them as complete. |
| Energy infrastructure | Power stations, primary substations, distribution transformers, 33/66/132/220 kV transmission lines, unidentified network, existing and under-development mini-grids | Asset inventory and geometric exposure analysis. Completeness, ownership and publication dates may vary by source. |
| Critical services | Schools and healthcare facilities | Context for potential service consequences. Proximity does not verify that an asset supplies a facility. |
| Hydrography | Kenya rivers and lakes | Geographic context and optional permanent-water screening. |
| Flood references | Kenya November 2023 Earth Engine reference; bundled 2024 UNOSAT event package | Observed/reference footprints stored separately from modeled flood candidates. The 2024 source is not field-validated and must not be treated as error-free ground truth. |
| Standalone GEE CGF-ACI outputs | `projects/osea-hack/assets/composite_hazard_raster`, `kenya_wards_vulnerability_vector`, `vulnerable_substations_vector`, and `vulnerable_minigrids_vector` | Outputs of a separate GEE demo. They are not ingested into the OSEAS pipeline or production assessment tables. The independent tile-map integration can display them; see [`../../CGF_ACI.md`](../../CGF_ACI.md). |

Source owners should confirm licensing, dates, field meanings and refresh schedules where those details are not carried in the original data.

### Inputs to the standalone CGF-ACI GEE demo

The GEE script provided for the CGF-ACI demo loads these collections. They are not, by virtue of appearing here, pipeline-ingested assets.

| Group | GEE asset IDs |
| --- | --- |
| Administrative area | `projects/osea-hack/assets/osea/kenya_wards` |
| Energy assets | `projects/osea-hack/assets/osea/power-stations`; `projects/osea-hack/assets/osea/primary-substations`; `projects/osea-hack/assets/osea/distribution-transformer`; `projects/osea-hack/assets/osea/existing-mini-grids`; `projects/osea-hack/assets/osea/mini-grids-under-development` |
| Network lines | `projects/osea-hack/assets/osea/transmission-lines-220kv`; `projects/osea-hack/assets/osea/transmission-lines-132kv`; `projects/osea-hack/assets/osea/transmission-lines-66kv`; `projects/osea-hack/assets/osea/transmission-lines-33kv` |
| Critical services | `projects/osea-hack/assets/osea/healthcare-facilities`; `projects/osea-hack/assets/osea/schools` |
| Climate imagery | `UCSB-CHG/CHIRPS/DAILY` precipitation; `ECMWF/ERA5_LAND/DAILY_AGGR` `temperature_2m_max` |

The four GEE output assets listed above are user-provided hosted assets. The separate GEE script conditionally exports each when the target does not already exist; it does not delete or overwrite existing assets. See [`../../CGF_ACI.md`](../../CGF_ACI.md) for its formula, style, resolution and processing limitations.

## Climate, hazard and contextual sources

The keys and `retrieval_status` values in the registry are the current configured metadata. Status vocabulary is source-specific and may reflect an earlier processing snapshot; verify with live run records.

| Dataset key | Source | Intended role | Implementation note |
| --- | --- | --- | --- |
| `chirps_daily` | CHIRPS daily precipitation, Earth Engine | Rainfall observations and dated-event summaries | Event-window totals and anomalies are implemented. Rainfall is not flood extent. |
| `era5_land_daily` | ERA5-Land daily aggregates, Earth Engine | Reanalysis climate variables | Catalogued and can be smoke-checked; not a general daily climate analytics processor. |
| `era5_daily` | ERA5 daily aggregates, Earth Engine | Historical reanalysis context | Historical-only coverage in this Earth Engine product; not a near-real-time source. |
| `nasa_power_daily` | NASA POWER API | Daily meteorology, including heat context | T2M_MAX heat processing is implemented. It is coarse near-surface air temperature, not land-surface temperature. |
| `nasa_viirs_black_marble_monthly` | NASA VNP46A2 via Earth Engine | Quality-screened nighttime radiance | Monthly adapter and persisted summary path exist. Confirm a successful latest run before claiming its summaries are current. |
| `worldpop_global2_kenya_population_100m` | WorldPop Global2 R2025A | Population-count raster for event exposure | Download and population exposure processing are implemented. Estimates are not confirmed impacts or population served by an asset. |
| `sentinel1_grd` | Sentinel-1 GRD, Earth Engine | Radar flood screening | Bounded event screening exists; candidate outputs are not validated inundation. |
| `sentinel2_l1c` | Sentinel-2 L1C, Earth Engine | Prithvi flood/water candidate inference | Task-specific model path exists; Kenya accuracy remains unvalidated. |
| `sentinel2_sr` | Sentinel-2 Level-2A, Earth Engine | Optical source imagery | Registered/audited source; general optical change processing is not implemented. |
| `dem_glo30` | Copernicus DEM GLO-30 | Terrain and slope context | Used for the bounded Sentinel-1 flood screen; a complete national terrain product is not implied. |
| `surface_water` | JRC Global Surface Water | Persistent-water masking | Used as a supporting mask in flood workflows; not a flood observation. |
| `nasa_firms_active_fire` | NASA FIRMS | Active-fire detections | API adapter requires a server-side key. Detections are points, not fire perimeters or damage. |
| `modis_burned_area` | MODIS MCD64A1 | Burned-area observations | Registered; no complete OSEAS burned-area exposure processor. |
| `landsat8_l2` | Landsat 8 Collection 2 Level-2 | Potential land-surface temperature/optical context | Registered; no LST processor. QA, scale and offset handling are required before use. |
| `climate_projections_cds` | Copernicus Climate Data Store | Future climate projections | Blocked until account, model, scenario, variable, baseline and period are selected. |
| `worldclim_baseline` | WorldClim 2.1 | Historical climate baseline | Download and processing are not staged. |
| `copernicus_landcover` | Copernicus Global Land Service | Land-cover context | Product and resolution selection/adapter are pending. |
| `hydrosheds_rivers` | HydroSHEDS | River/drainage context | Product selection and staging are pending. |
| `openstreetmap_context` | OpenStreetMap | Infrastructure/waterway context | Adapter is not implemented; ODbL attribution applies. |
| `historical_flood_extents` | Copernicus EMS / UNOSAT | Event reference footprints | Event-specific products; use their validation and date metadata. |
| `historical_flood_events` | EM-DAT / ReliefWeb | Event records | Registration/access and spatial-detail review remain necessary; event records are not flood polygons. |
| `global_wind_atlas_*` | Global Wind Atlas country GeoTIFFs | Long-term wind resource context | Sync/cache/map endpoints exist. Resource potential is not a severe-wind hazard. |

## Raster resolutions and how grids are handled

The following are nominal source pixel spacings from the catalog/provider metadata. Values in metres are approximate, especially for products defined in angular degrees. A requested processing scale, map display scale or export pixel size is not the same as the input's native information resolution.

| Raster/source | Nominal source resolution | Processing/resolution handling |
| --- | ---: | --- |
| CHIRPS daily precipitation | 0.05°; catalog approx. 5,566 m | Rainfall summaries request 5,566 m in Earth Engine and reduce event-window totals over administrative polygons. The independent CGF-ACI export requests 1,000 m but does not downscale the rainfall information. |
| ERA5-Land daily aggregates | 0.1°; catalog approx. 11,132 m | Registered source; no general OSEAS daily raster analytics processor. The separate CGF-ACI calculation uses `temperature_2m_max`. |
| ERA5 daily aggregates | 0.25°; catalog approx. 27,830 m | Registered context source; no general daily analytics processor. |
| VIIRS VNP46A2 Black Marble | 500 m nominal; downloaded on a 15-arc-second grid (`1/240°`) | Quality-screened monthly images are mosaicked on the same grid; zonal summaries use `exactextract` rather than reprojecting to a finer grid. Asset/service context uses a 500 m buffer. |
| WorldPop Global2 R2025A | 100 m; 3 arc-seconds | Population-count cells are read in the source EPSG:4326 grid. Pixel centers determine inclusion; valid cell counts are summed. No raster resampling is performed by the zonal calculation. |
| NASA POWER daily | Approx. 0.5° / 50 km regional grid | Asset context selects the nearest provider grid cell within 45 km; it does not interpolate to asset scale. |
| WorldClim 2.1 baseline | Catalog approx. 1,000 m | Download/processing is not staged; no OSEAS resampling method is established. |
| Copernicus DEM GLO-30 | 30 m | Used as a terrain input to bounded Sentinel-1 screening; the 30 m DEM does not make the resulting flood candidates validated inundation. |
| Sentinel-1 GRD | 10 m nominal | Event/baseline median and a 20 m-radius focal median are used; vectorization requests 20 m. This is a screening configuration, not a universal 10 m output guarantee. |
| Sentinel-2 L1C selected Prithvi bands | B2/B3/B4: 10 m; B8A/B11/B12: 20 m | Earth Engine exports the model input at 10 m in a UTM CRS. Native 20 m bands are reprojected with nearest-neighbour sampling; this aligns the tensor grid but does not add 10 m detail to those bands. |
| Sentinel-2 SR | Bands vary, commonly 10/20/60 m | Registered/audited source; no general resampling workflow is implemented. |
| Landsat 8 Level-2 | 30 m reflective bands; thermal native grid is coarser (100 m, distributed on a 30 m grid) | Registered only for potential use; no OSEAS LST processor or common-grid resampling is implemented. |
| JRC Global Surface Water | 30 m | Used as a water-occurrence mask in flood screening; alignments follow the consuming Earth Engine operation. |
| MODIS MCD64A1 burned area | 500 m | Registered context source; no complete OSEAS burned-area exposure workflow. |
| Copernicus land cover | Catalog product selection approx. 100 m | Product/year not selected; no OSEAS resampling workflow. |
| Global Wind Atlas | 250 m | Cached GeoTIFFs retain product grid; these are renewable-resource context, not a hazard layer. |
| CGF-ACI composite output | Export requested at 1,000 m in EPSG:4326 | Standalone GEE display/output grid derived from about 5.6 km CHIRPS and 11 km ERA5-Land. The code does not request a named resampler; Earth Engine's default nearest-neighbour behavior applies where reprojection is needed. A 1 km export is not a 1 km climate analysis. |

There is no single common raster grid across OSEAS sources. Where the code explicitly requests a different grid, the method is recorded above. Outside the documented Sentinel-2 and CGF-ACI cases, do not assume a resampling algorithm: inspect the processor and its run metadata. For new multi-raster analyses, explicitly document CRS, transform/alignment, pixel size, resampler, masks and nodata policy. Nearest neighbour is appropriate for categorical values and masks; continuous variables need a documented, scientifically appropriate method. Resampling changes the raster representation, not the underlying information content.

## Live map tiles and raster analysis are different

For configured GEE image assets and selected public image collections, the backend can create temporary Earth Engine map tile URLs for ArcGIS visualization. Those tiles can show a layer but do not provide pixel values, feature attributes, or zonal statistics. A displayed raster value must come from a supported identify/query operation or a server-side raster calculation, never from the rendered color.

## Acceptance rules

- Catalog registration is not retrieval.
- An audit/smoke test is not a persisted assessment.
- A successful ingestion is not proof that every feature is valid or complete.
- Empty, missing or low-coverage output is not a measured zero.
- Every derived result should be interpreted with its actual source period, spatial coverage, method and quality status.

For processing methods see [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md); for run acceptance see [`PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md).
