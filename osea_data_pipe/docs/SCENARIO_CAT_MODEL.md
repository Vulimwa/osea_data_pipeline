# Kano flood-risk demo and CAT model status

The Kano Plains map is a pilot view of the `osm_kano_pilot` inventory. It focuses the demo on the Kano/Nyando area; it does not mean every OSEAS dataset or assessment covers that area. Check a layer's run, dates and coverage before presenting its result.

## CAT model and vulnerability workflow

The Energy Infrastructure Vulnerability Dataset workflow and CAT model are implemented in the separate [OSEAS climate-risk-infrastructure-vulnerability repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability). That repository owns the model implementation; its data is held in the same database used by this OSEAS project. The code is not part of this repository's pipeline. Consult the linked repository for the model's actual methods, configuration, outputs and validation status.

The CAT model is distinct from the flood-evidence workflows in this repository. Here, the bounded Sentinel-1 change screen and Prithvi-EO workflow produce flood/water candidate evidence and spatial exposure. They do not, on their own, establish a return-period flood depth, asset damage, outage duration or expected loss. See the [flood model card](MODEL_CARD.md).

## CGF-ACI is separate from CAT

The CGF-ACI analysis was processed independently in Google Earth Engine and its four outputs are hosted:

- `projects/osea-hack/assets/composite_hazard_raster`
- `projects/osea-hack/assets/kenya_wards_vulnerability_vector`
- `projects/osea-hack/assets/vulnerable_substations_vector`
- `projects/osea-hack/assets/vulnerable_minigrids_vector`

CGF-ACI is not the CAT model and is not yet an OSEAS pipeline stage. Its separate GEE tile integration can display hosted layers, but that display does not itself ingest the GEE outputs into PostGIS or create OSEAS assessment records. CGF-ACI is an exploratory climate-exposure indicator, not a catastrophe model: it does not simulate electrical cascade propagation, equipment failure, flood depth or service interruption.

The [CGF-ACI technical note](../../CGF_ACI.md) documents its input assets, formulas, source and output resolutions, styles, assumptions and limits.

## Data and integration boundary

The CAT model and OSEAS share the project database, but sharing a database does not make the model implementation part of this repository's processing code. Preserve source, run and model provenance when reading or displaying CAT outputs. Do not equate a raster tile or database record with a validated result; confirm its model version, dates, study area, coverage, assumptions and confidence.

For this repository's processing and API behavior, see [pipeline contracts](PIPELINE_CONTRACTS.md) and [API contracts](API_CONTRACTS.md). For the separately implemented model, use the documentation in the [vulnerability-workflow repository](https://github.com/Nosh-thee-techy/oseas26-climate-risk-infrastructure-vulnerability).
