# OSEAS documentation

Use these documents as a practical guide to the running system. Source code, the live API and the latest processing-run records are authoritative when a documented example or status snapshot is older.

## Start here

- [System architecture](ARCHITECTURE.md): components and flow of data.
- [Dataset catalog](DATA_CATALOG.md): source families, adapters and status.
- [Assessment methods](ASSESSMENT_METHODS.md): what is calculated and how to interpret it.
- [Model card](MODEL_CARD.md): OSEAS flood model details; CGF-ACI is explicitly separate from the pipeline.
- [CGF-ACI GEE note](../../CGF_ACI.md): standalone demo inputs/outputs, formulas, resolutions, display and limitations.
- [Scenario and catastrophe modelling](SCENARIO_CAT_MODEL.md): Kano pilot status and the boundary between this pipeline's flood screening, the CAT model in the separate vulnerability-workflow repository, and CGF-ACI.
- [Setup](SETUP.md): prerequisites, secrets and schema setup.
- [End-to-end runbook](END_TO_END_RUNBOOK.md): commands, order of operations and recovery.
- [Pipeline contracts](PIPELINE_CONTRACTS.md): stage inputs, outputs and acceptance conditions.
- [API contracts](API_CONTRACTS.md): endpoints, filters and response behavior.
- [Frontend integration](FRONTEND_INTEGRATION_GUIDE.md): map, evidence and UI data integration.
- [Connect to Supabase and Earth Engine](CONNECT.md): short configuration reference.

At repository level, [README](../README.md) provides the project overview and [`../../OUTPUTS.md`](../../OUTPUTS.md) summarizes the delivered scope.

## Reading status correctly

The data catalog is not a live service monitor. A registered source may not yet have an adapter or successful persisted run. Check `/api/v1/oseas/readiness`, `/api/v1/oseas/runs`, and source-specific run/quality records before claiming a product is current. A `not_assessed` result means evidence is absent or insufficient; it does not mean zero hazard.
