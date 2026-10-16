# OSEAS pipeline runbook

This runbook covers the normal path from configuration to published evidence. Do not start a full processing run until credentials, schema, source access and the intended analysis period have been checked. Nationwide Prithvi processing can take many hours.

For a description of each stage's inputs and acceptance conditions, see [`PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md). For source-specific calculations and limitations, see [`ASSESSMENT_METHODS.md`](ASSESSMENT_METHODS.md).

## 1. Prepare the environment

Follow [`SETUP.md`](SETUP.md) to install dependencies and configure backend-only secrets. Apply [`../database/schema.sql`](../database/schema.sql) to PostGIS, then confirm connectivity and schema:

```powershell
npm run db:setup
```

Do not expose database URLs, service-role keys, Earth Engine keys, or NASA API keys in logs, screenshots, or frontend environment variables.

## 2. Audit source access

```powershell
npm run oseas:audit
npm run oseas:catalog:audit
```

The asset audit checks configured Earth Engine table access and source schemas. The catalog audit performs a bounded smoke check of selected public Earth Engine collections. These audits do not write source features to PostGIS, calculate a national product, or validate a model.

## 3. Ingest and assign inventory

```powershell
npm run oseas:ingest
npm run oseas:assign-admin
npm run oseas:status
```

Ingestion writes source features in bounded pages and records run, version and quality metadata. Stable source keys make retries idempotent; ingestion does not delete database rows absent from the latest source snapshot. Review every source's terminal status and skipped geometry counts. Assignment requires usable current county and ward boundaries.

## 4. Run only the required evidence workflows

Choose workflows that match the question, source availability and time budget. Examples:

```powershell
npm run oseas:rainfall
npm run oseas:heat
npm run oseas:nightlights
npm run oseas:fire
npm run oseas:population:audit
npm run oseas:population:download
npm run oseas:population:persist
npm run oseas:assessments
```

WorldPop persistence requires a downloaded/validated raster, flood-reference footprints, administrative boundaries and the database schema. FIRMS requires its server-side API key. Other workflows have their own date, coverage and credential prerequisites. Review the relevant source sections in [`DATA_CATALOG.md`](DATA_CATALOG.md) and the method before treating an output as available.

`npm run oseas:run` orchestrates configured stages. It may synchronize wind rasters, prepare model resources, ingest or reuse inventory, and run processors depending on configuration. It is not a quick startup command. Check its stage report and terminal statuses instead of assuming every stage ran successfully.

## 5. Optional flood processing

The Sentinel-1 screen requires an explicit small-area bounding box, event interval and baseline interval. Example command shape:

```powershell
npm run oseas:flood:screen -- --bbox <west> <south> <east> <north> `
  --event-start YYYY-MM-DD --event-end YYYY-MM-DD `
  --baseline-start YYYY-MM-DD --baseline-end YYYY-MM-DD
```

The processor is bounded (maximum 1,000 km² and 45 days per window). It checks same-orbit coverage, terrain and persistent-water masks. Outputs are modeled flood candidates. They are not confirmed inundation, calibrated flood probability, asset damage or outage.

The bounded Prithvi pilot is limited to 5 km²:

```powershell
npm run oseas:prithvi:setup
npm run oseas:prithvi:flood -- --bbox <west> <south> <east> <north> `
  --event-start YYYY-MM-DD --event-end YYYY-MM-DD
```

Prithvi nationwide mode is a separate resumable tiled workflow. It can be started through `npm run oseas:prithvi:national` or by the orchestrator when event dates are configured. Read [`MODEL_CARD.md`](MODEL_CARD.md) before running it; national accuracy is not validated.

## 6. Verify the results

After each run:

1. Inspect the terminal summary and any generated stage report under `outputs/`.
2. Run `npm run oseas:status`.
3. Check `/api/v1/oseas/readiness` and `/api/v1/oseas/runs`.
4. Confirm the intended period, spatial coverage, row counts, quality warnings and provenance for each output.
5. Stop if a prerequisite failed; do not interpret stale downstream rows as results from the failed run.

An empty result may mean no source data, no valid observations, no geometric intersections, or a completed analysis with no candidate features. Use its explicit status and provenance to tell these cases apart. Never present `not_assessed` as a measured zero.

## 7. Serve the API and frontend

Start the API from this directory:

```powershell
npm run dev
```

Start the map separately from `frontend`:

```powershell
npm run dev
```

The API serves read-only data under `/api/v1/oseas`. Production access uses bearer-token validation unless `OSEAS_PUBLIC_READ_API=true` explicitly enables public GET access. The map may also request temporary Earth Engine map tiles through the backend; those are visual tiles, not a substitute for feature queries or raster identify. See [`API_CONTRACTS.md`](API_CONTRACTS.md) and [`FRONTEND_INTEGRATION_GUIDE.md`](FRONTEND_INTEGRATION_GUIDE.md).

## Safe retry and interruption handling

Page writes and stable IDs allow inventory ingestion to be retried. Before restarting a long workflow, confirm that no writer is still active using `npm run oseas:status` and the process/operator's normal monitoring. Do not remove lock files or mark a run stale while its worker may still be alive. After interruption, inspect the run state, rerun the relevant idempotent stage, and verify its final database output before running dependent stages.

## Troubleshooting

- **Authentication or asset access:** check the configured identity, Earth Engine project, full asset ID and access grants.
- **No source images:** choose a period with actual product coverage; do not interpret an empty collection as zero hazard.
- **Coverage gate failed:** use a smaller AOI or a supported period. Keep uncovered areas unassessed.
- **Geometry warnings:** review source geometry type and quality details; do not claim the inventory is complete until resolved or documented.
- **Missing table/column:** apply the current additive SQL schema, then run `npm run db:setup`.
- **Unexpectedly long run:** confirm the process and stage. Nationwide tiling and multiyear raster work are expected to take much longer than API queries.
