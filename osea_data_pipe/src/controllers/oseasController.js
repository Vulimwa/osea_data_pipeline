'use strict';

const fs = require('fs');
const path = require('path');
const db = require('../repositories/db');
const { AppError } = require('../middleware/errorHandler');
const catalog = require('../../config/data_catalog.json');

const windProducts = {
  wind_speed_10m: { file: 'wind_speed_10m_map.tif', unit: 'm/s', datasetKey: 'global_wind_atlas_wind_speed_10m' },
  power_density_10m: { file: 'power_density_10m_map.tif', unit: 'W/m2', datasetKey: 'global_wind_atlas_power_density_10m' },
  air_density_10m: { file: 'air_density_10m_map.tif', unit: 'kg/m3', datasetKey: 'global_wind_atlas_air_density_10m' },
};
const windCacheDir = path.resolve(__dirname, '../..', 'data/raw/global_wind_atlas/KEN');
const mapLayerSql = {
  climate_observations: `SELECT id::text AS id,geom,jsonb_build_object('datasetKey',dataset_key,'variable',variable,'value',value,'unit',unit,'observedAt',observed_at,'processingRunId',processing_run_id) AS properties FROM climate_observations`,
  climate_projections: `SELECT id::text AS id,geom,jsonb_build_object('datasetKey',dataset_key,'variable',variable,'value',value,'unit',unit,'scenario',scenario,'modelName',model_name,'periodStart',period_start,'periodEnd',period_end,'processingRunId',processing_run_id) || metadata AS properties FROM climate_projections`,
  terrain: `SELECT id::text AS id,geom,jsonb_build_object('datasetKey',dataset_key,'elevationM',elevation_m,'slopeDegrees',slope_degrees,'drainageDistanceM',drainage_distance_m,'processingRunId',processing_run_id) || metadata AS properties FROM terrain_metrics`,
  land_cover: `SELECT id::text AS id,geom,jsonb_build_object('datasetKey',dataset_key,'classCode',class_code,'className',class_name,'proportion',proportion,'periodStart',period_start,'periodEnd',period_end,'processingRunId',processing_run_id) || metadata AS properties FROM land_cover_metrics`,
  fire: `SELECT h.id::text AS id,h.geom,jsonb_build_object('hazardType',h.hazard_type,'evidenceKind',h.evidence_kind,'eventStart',h.event_start,'eventEnd',h.event_end,'source',h.source_reference,'confidence',f.confidence,'burnedAreaHa',f.burned_area_ha,'fireStatus',f.fire_status,'quality',f.quality,'metadata',h.metadata,'processingRunId',h.processing_run_id) AS properties FROM hazard_events h LEFT JOIN fire_events f ON f.hazard_event_id=h.id WHERE h.hazard_type IN ('fire','wildfire')`,
  asset_exposure: `SELECT e.id::text AS id,a.geom,jsonb_build_object('energyAssetId',a.id,'assetType',a.asset_type,'assetName',a.name,'hazardType',e.hazard_type,'hazardEventId',e.hazard_event_id,'assessmentPeriodStart',e.assessment_period_start,'assessmentPeriodEnd',e.assessment_period_end,'exposureStatus',e.exposure_status,'intersectionAreaM2',e.intersection_area_m2,'intersectionLengthM',e.intersection_length_m,'distanceM',e.distance_m,'evidenceKind',e.evidence_kind,'confidence',e.confidence,'provenance',e.provenance,'processingRunId',e.processing_run_id) AS properties FROM asset_hazard_exposure e JOIN energy_assets a ON a.id=e.energy_asset_id`,
  asset_vulnerability: `SELECT v.id::text AS id,a.geom,jsonb_build_object('energyAssetId',a.id,'assetType',a.asset_type,'assetName',a.name,'status',v.status,'vulnerabilityClass',v.vulnerability_class,'score',v.score,'sensitivity',v.sensitivity,'adaptiveCapacity',v.adaptive_capacity,'missingEvidence',v.missing_evidence,'confidence',v.confidence,'method',v.method,'provenance',v.provenance,'processingRunId',v.processing_run_id) AS properties FROM asset_vulnerability_assessments v JOIN energy_assets a ON a.id=v.energy_asset_id`,
  asset_criticality: `SELECT c.id::text AS id,a.geom,jsonb_build_object('energyAssetId',a.id,'assetType',a.asset_type,'assetName',a.name,'status',c.status,'score',c.score,'method',c.method,'evidence',c.evidence,'confidence',c.confidence,'processingRunId',c.processing_run_id) AS properties FROM asset_criticality_assessments c JOIN energy_assets a ON a.id=c.energy_asset_id`,
  service_dependencies: `SELECT d.id::text AS id,a.geom,jsonb_build_object('energyAssetId',a.id,'assetType',a.asset_type,'assetName',a.name,'criticalServiceId',s.id,'serviceType',s.service_type,'serviceName',s.name,'verified',d.verified,'confidence',d.confidence,'evidenceDatasetKey',d.evidence_dataset_key,'evidence',d.evidence) AS properties FROM service_dependencies d JOIN energy_assets a ON a.id=d.energy_asset_id JOIN critical_services s ON s.id=d.critical_service_id`,
  administrative_summaries: `SELECT s.id::text AS id,u.geom,jsonb_build_object('administrativeUnitId',u.id,'level',u.unit_level,'name',u.name,'hazardType',s.hazard_type,'eventFingerprint',s.event_fingerprint,'periodStart',s.period_start,'periodEnd',s.period_end,'assessmentStatus',s.assessment_status,'assignedAssets',s.assigned_energy_asset_count,'candidateExposedAssets',s.candidate_exposed_asset_count,'exposureFraction',s.candidate_exposure_fraction,'provenance',s.provenance,'processingRunId',s.processing_run_id) AS properties FROM administrative_hazard_summaries s JOIN administrative_units u ON u.id=s.administrative_unit_id`,
  interventions: `SELECT i.id::text AS id,COALESCE(i.area,a.geom) AS geom,jsonb_build_object('energyAssetId',i.energy_asset_id,'action',i.action,'priority',i.priority,'status',i.status,'reason',i.reason,'evidence',i.evidence,'assumptions',i.assumptions,'confidence',i.confidence,'processingRunId',i.processing_run_id) AS properties FROM intervention_scenarios i LEFT JOIN energy_assets a ON a.id=i.energy_asset_id`,
  population_exposure: `SELECT id::text AS id,geom,jsonb_build_object('datasetKey',dataset_key,'hazardEventId',hazard_event_id,'reportingUnitId',reporting_unit_id,'populationTotal',population_total,'populationPotentiallyExposed',population_potentially_exposed,'assessmentStatus',assessment_status,'method',method,'evidence',evidence,'confidence',confidence,'processingRunId',processing_run_id) AS properties FROM population_exposure_assessments`,
  grid_resilience: `SELECT id::text AS id,geom,jsonb_build_object('energyAssetId',energy_asset_id,'reportingUnitId',reporting_unit_id,'assessmentStatus',assessment_status,'score',score,'criteria',criteria,'method',method,'evidence',evidence,'confidence',confidence,'processingRunId',processing_run_id) AS properties FROM grid_resilience_assessments`,
  coverage: `SELECT id::text || ':observation' AS id,observation_footprint AS geom,jsonb_build_object('coverageId',id,'footprintType','observation','datasetKey',dataset_key,'processingRunId',processing_run_id,'reportingUnitId',reporting_unit_id,'reportingUnitLevel',reporting_unit_level,'hazardType',hazard_type,'evidenceKind',evidence_kind,'observationStart',observation_start,'observationEnd',observation_end,'coverageStatus',coverage_status,'areaCoverageFraction',area_coverage_fraction,'validDataFraction',valid_data_fraction,'qualityMask',quality_mask,'validationStatus',validation_status,'limitations',limitations,'provenance',provenance) AS properties FROM spatial_coverage_assessments UNION ALL SELECT id::text || ':valid' AS id,valid_data_footprint AS geom,jsonb_build_object('coverageId',id,'footprintType','valid_data','datasetKey',dataset_key,'processingRunId',processing_run_id,'reportingUnitId',reporting_unit_id,'reportingUnitLevel',reporting_unit_level,'hazardType',hazard_type,'evidenceKind',evidence_kind,'observationStart',observation_start,'observationEnd',observation_end,'coverageStatus',coverage_status,'areaCoverageFraction',area_coverage_fraction,'validDataFraction',valid_data_fraction,'qualityMask',quality_mask,'validationStatus',validation_status,'limitations',limitations,'provenance',provenance) AS properties FROM spatial_coverage_assessments`,
};

const asyncRoute = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function pagination(query) {
  const limit = Math.min(500, Math.max(1, Number.parseInt(query.limit, 10) || 100));
  const offset = Math.max(0, Number.parseInt(query.offset, 10) || 0);
  return { limit, offset };
}

function bboxFilter(raw, firstIndex) {
  if (!raw) return { sql: '', params: [] };
  const values = String(raw).split(',').map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value)) || values[0] < -180 || values[2] > 180 || values[1] < -90 || values[3] > 90 || values[0] >= values[2] || values[1] >= values[3]) {
    throw new AppError('INVALID_BBOX', 'bbox must be minLon,minLat,maxLon,maxLat in EPSG:4326', 400);
  }
  return { sql: ` AND ST_Intersects(geom, ST_MakeEnvelope($${firstIndex},$${firstIndex + 1},$${firstIndex + 2},$${firstIndex + 3},4326))`, params: values };
}

function validateUuid(value, label = 'id') {
  if (!uuidPattern.test(value)) throw new AppError('INVALID_ID', `${label} must be a UUID`, 400);
}

function parseJson(value, fallback = null) {
  if (value == null) return fallback;
  return typeof value === 'string' ? JSON.parse(value) : value;
}

const getReadiness = asyncRoute(async (_req, res) => {
  const database = await db.checkHealth();
  let sourceRun = null;
  let latestFloodRun = null;
  let tableStatus = {};
  let sourceCounts = {};
  if (database.connected) {
    const result = await db.query(`
      SELECT to_regclass('public.energy_assets') IS NOT NULL AS assets,
             to_regclass('public.administrative_units') IS NOT NULL AS boundaries,
             to_regclass('public.asset_admin_assignments') IS NOT NULL AS assignments,
             to_regclass('public.hazard_events') IS NOT NULL AS hazards,
             to_regclass('public.administrative_hazard_summaries') IS NOT NULL AS summaries,
             to_regclass('public.hydrography_features') IS NOT NULL AS hydrography,
             to_regclass('public.flood_reference_features') IS NOT NULL AS flood_reference,
             to_regclass('public.spatial_coverage_assessments') IS NOT NULL AS coverage,
             to_regclass('public.population_exposure_assessments') IS NOT NULL AS population_exposure,
             to_regclass('public.grid_resilience_assessments') IS NOT NULL AS grid_resilience
    `);
    tableStatus = result.rows[0];
    const sources = await db.query(`SELECT status,started_at,finished_at,metadata FROM ingestion_runs WHERE pipeline_name='oseas_earth_engine_ingest' ORDER BY started_at DESC LIMIT 1`);
    sourceRun = sources.rows[0] || null;
    const flood = await db.query(`
      SELECT r.id,r.status,r.started_at,r.finished_at,r.metadata,
             count(DISTINCT h.id)::int AS polygon_count,
             count(DISTINCT e.id)::int AS exposure_count
      FROM ingestion_runs r
      LEFT JOIN hazard_events h ON h.processing_run_id=r.id AND h.hazard_type='flood'
      LEFT JOIN asset_hazard_exposure e ON e.processing_run_id=r.id AND e.hazard_type='flood'
      WHERE r.pipeline_name IN ('oseas_sentinel1_flood_screen','oseas_prithvi_flood_screen')
      GROUP BY r.id ORDER BY r.started_at DESC LIMIT 1
    `).catch(() => ({ rows: [] }));
    latestFloodRun = flood.rows[0] || null;
    const counts = await db.query(`
      SELECT (SELECT count(*)::int FROM energy_assets) AS energy_assets,
             (SELECT count(*)::int FROM critical_services) AS critical_services,
             (SELECT count(*)::int FROM administrative_units WHERE unit_level='ward') AS wards,
             (SELECT count(*)::int FROM administrative_units WHERE unit_level='county') AS counties,
             (SELECT count(*)::int FROM hydrography_features) AS hydrography_features,
             (SELECT count(*)::int FROM flood_reference_features) AS flood_reference_features
    `).catch(() => ({ rows: [{}] }));
    sourceCounts = counts.rows[0];
  }
  const prithviModelDir = path.resolve(__dirname, '../..', process.env.PRITHVI_MODEL_DIR || 'models/prithvi/flood_sen1floods11');
  const prithviCheckpoint = path.join(prithviModelDir, 'Prithvi-EO-V2-300M-TL-Sen1Floods11.pt');
  const inventoryReady = tableStatus.assets === true && tableStatus.boundaries === true;
  const schemaReady = inventoryReady && tableStatus.assignments === true && tableStatus.hazards === true && tableStatus.summaries === true && tableStatus.hydrography === true && tableStatus.flood_reference === true && tableStatus.coverage === true && tableStatus.population_exposure === true && tableStatus.grid_resilience === true;
  const apiReady = database.connected === true && schemaReady;
  res.json({
    service: 'oseas-climate-risk-api',
    status: apiReady ? 'ready_with_limitations' : 'blocked',
    apiReadyForIntegration: apiReady,
    checks: {
      database: database.connected ? { status: 'ok', postgisVersion: database.postgis_version } : { status: 'unavailable' },
      sourceIngestion: sourceRun ? { status: sourceRun.status, startedAt: sourceRun.started_at, finishedAt: sourceRun.finished_at } : { status: 'not_run' },
      sourceCounts,
      inventory: { status: inventoryReady ? 'available' : 'incomplete' },
      outputSchema: { status: schemaReady ? 'installed' : 'incomplete', tables: tableStatus },
      latestFloodScreen: latestFloodRun ? { status: latestFloodRun.status, runId: latestFloodRun.id, candidatePolygons: latestFloodRun.polygon_count, exposureRows: latestFloodRun.exposure_count } : { status: 'not_run' },
      usableHazardOutputs: Boolean(latestFloodRun && ['completed', 'partial'].includes(latestFloodRun.status) && Number(latestFloodRun.polygon_count) > 0),
      earthEngine: { configured: Boolean(process.env.GEE_PROJECT_ID), liveConnection: 'not_checked_by_readiness' },
      prithvi: { status: fs.existsSync(prithviCheckpoint) ? 'configured_not_validated' : 'model_bundle_not_downloaded', checkpointAvailable: fs.existsSync(prithviCheckpoint), model: 'Prithvi-EO-2.0-300M-TL-Sen1Floods11', task: 'Sentinel-2 L1C flood segmentation', validatedForKenya: false, reason: fs.existsSync(prithviCheckpoint) ? 'Task checkpoint is present; no independent Kenya validation has been completed' : 'Run npm run oseas:prithvi:setup to fetch the pinned task checkpoint' },
      hazardScope: 'Bounded Sentinel-1 relative-backscatter screening and Sentinel-2 Prithvi flood-candidate mapping are available; no calibrated risk, heat, wildfire, outage, or resilience scores are implied.'
    },
    timestamp: new Date().toISOString()
  });
});

const getCatalog = asyncRoute(async (_req, res) => {
  const dbRows = await db.query('SELECT dataset_key,last_ingested_at FROM datasets ORDER BY dataset_key').catch(() => ({ rows: [] }));
  const byKey = new Map(dbRows.rows.map((row) => [row.dataset_key, row.last_ingested_at]));
  const windCached = fs.existsSync(path.join(windCacheDir, 'manifest.json'));
  res.json({ data: catalog.map((source) => ({ ...source, retrieval_status: byKey.has(source.key) ? 'retrieved_in_persisted_run' : (windCached && source.key.startsWith('global_wind_atlas_') ? 'retrieved_and_cached' : source.retrieval_status), lastSuccessfulRun: byKey.get(source.key) || null })), count: catalog.length });
});

const getRuns = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const rows = await db.query(`
    SELECT r.id,r.pipeline_name,r.status,r.started_at,r.finished_at,r.metadata,r.error_message,
           m.id AS model_run_id,m.model_name,m.model_version,m.task,m.metrics,m.parameters
    FROM ingestion_runs r LEFT JOIN model_runs m ON m.processing_run_id=r.id
    WHERE r.pipeline_name LIKE 'oseas_%'
    ORDER BY r.started_at DESC LIMIT $1 OFFSET $2
  `, [limit, offset]);
  res.json({ data: rows.rows.map((row) => ({ ...row, metadata: parseJson(row.metadata, {}), metrics: parseJson(row.metrics, {}), parameters: parseJson(row.parameters, {}) })), pagination: { limit, offset } });
});

const getRun = asyncRoute(async (req, res) => {
  validateUuid(req.params.id);
  const run = await db.query(`
    SELECT r.*,m.id AS model_run_id,m.model_name,m.model_version,m.task,m.parameters,m.metrics,m.status AS model_status,m.checkpoint
    FROM ingestion_runs r LEFT JOIN model_runs m ON m.processing_run_id=r.id WHERE r.id=$1
  `, [req.params.id]);
  if (!run.rows.length) throw new AppError('NOT_FOUND', 'OSEAS run was not found', 404);
  const checks = await db.query('SELECT dataset_key,check_name,status,details,checked_at FROM data_quality_checks WHERE run_id=$1 ORDER BY checked_at', [req.params.id]);
  const item = run.rows[0];
  res.json({ data: { ...item, metadata: parseJson(item.metadata, {}), parameters: parseJson(item.parameters, {}), metrics: parseJson(item.metrics, {}), qualityChecks: checks.rows.map((row) => ({ ...row, details: parseJson(row.details, {}) })) } });
});

const getLayers = asyncRoute(async (_req, res) => {
  const result = await db.query(`
    SELECT hazard_type,evidence_kind,count(*)::int AS feature_count,max(processing_run_id::text) AS latest_processing_run_id
    FROM hazard_events GROUP BY hazard_type,evidence_kind ORDER BY hazard_type,evidence_kind
  `);
  const storedOutputs = Object.keys(mapLayerSql).map((layer) => ({ layer, evidenceKind: 'stored_derived_output', geometry: 'GeoJSON geometry', crs: 'EPSG:4326', endpoint: `/api/v1/oseas/layers/${layer}/geojson`, status: 'queryable_not_assessed_until_rows_exist' }));
  const referenceLayers = [
    { layer: 'flood_reference', evidenceKind: 'reference_observation', endpoint: '/api/v1/oseas/layers/flood_reference/geojson' },
    { layer: 'hydrography_rivers_lakes', evidenceKind: 'reference_hydrography', endpoint: '/api/v1/oseas/layers/hydrography/geojson' },
    { layer: 'wind_resource', evidenceKind: 'renewable_resource', endpoint: '/api/v1/oseas/layers/wind_resource' },
  ];
  res.json({ data: [
    ...result.rows.map((row) => ({ ...row, geometry: 'GeoJSON geometry', crs: 'EPSG:4326', endpoint: row.hazard_type === 'flood' ? '/api/v1/oseas/layers/flood_candidate/geojson' : (['fire', 'wildfire'].includes(row.hazard_type) ? '/api/v1/oseas/layers/fire/geojson' : null) })),
    ...referenceLayers.map((row) => ({ ...row, geometry: 'GeoJSON geometry', crs: 'EPSG:4326' })), ...storedOutputs,
  ] });
});

const getFloodGeoJson = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const filter = bboxFilter(req.query.bbox, 2);
  const latest = await db.query("SELECT id,status,metadata FROM ingestion_runs WHERE pipeline_name IN ('oseas_sentinel1_flood_screen','oseas_prithvi_flood_screen') AND status IN ('completed','partial') ORDER BY started_at DESC LIMIT 1");
  if (!latest.rows.length) return res.json({ type: 'FeatureCollection', features: [], count: 0, pagination: { limit, offset }, spatialReference: 'EPSG:4326', status: 'not_assessed' });
  const params = [latest.rows[0].id, ...filter.params, limit, offset];
  const filterSql = filter.sql;
  const limitIndex = 2 + filter.params.length;
  const totalResult = await db.query(`SELECT count(*)::int AS total FROM hazard_events WHERE processing_run_id=$1 AND hazard_type='flood'${filterSql}`, [latest.rows[0].id, ...filter.params]);
  const result = await db.query(`
    SELECT id,hazard_type,evidence_kind,event_start,event_end,source_reference,confidence,metadata,ST_AsGeoJSON(geom)::json AS geometry
    FROM hazard_events WHERE processing_run_id=$1 AND hazard_type='flood'${filterSql}
    ORDER BY id LIMIT $${limitIndex} OFFSET $${limitIndex + 1}
  `, params);
  const features = result.rows.map((row) => ({ type: 'Feature', id: row.id, geometry: row.geometry, properties: { hazardType: row.hazard_type, evidenceKind: row.evidence_kind, eventStart: row.event_start, eventEnd: row.event_end, source: row.source_reference, confidence: row.confidence, metadata: parseJson(row.metadata, {}) } }));
  res.json({ type: 'FeatureCollection', features, count: features.length, pagination: { total: totalResult.rows[0].total, limit, offset }, processingRunId: latest.rows[0].id, processingStatus: latest.rows[0].status, runMetadata: parseJson(latest.rows[0].metadata, {}), spatialReference: 'EPSG:4326' });
});

const getHydrographyGeoJson = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const filter = bboxFilter(req.query.bbox, 2);
  const allowed = { river: 'river', lake: 'lake' };
  const type = req.query.type ? String(req.query.type).toLowerCase() : null;
  if (type && !allowed[type]) throw new AppError('INVALID_TYPE', 'type must be river or lake', 400);
  const values = [];
  const predicates = [];
  if (type) { values.push(allowed[type]); predicates.push(`feature_type=$${values.length}`); }
  if (req.query.bbox) {
    values.push(...filter.params);
    predicates.push(`ST_Intersects(geom, ST_MakeEnvelope($${values.length - 3},$${values.length - 2},$${values.length - 1},$${values.length},4326))`);
  }
  const where = predicates.length ? `WHERE ${predicates.join(' AND ')}` : '';
  const count = await db.query(`SELECT count(*)::int AS total FROM hydrography_features ${where}`, values);
  const rows = await db.query(`SELECT id,dataset_key,source_feature_id,feature_type,name,source_properties,processing_run_id,ST_AsGeoJSON(geom)::json AS geometry FROM hydrography_features ${where} ORDER BY id LIMIT $${values.length + 1} OFFSET $${values.length + 2}`, [...values, limit, offset]);
  const features = rows.rows.map((row) => ({ type: 'Feature', id: row.id, geometry: row.geometry, properties: { featureType: row.feature_type, name: row.name, datasetKey: row.dataset_key, sourceFeatureId: row.source_feature_id, sourceProperties: parseJson(row.source_properties, {}), processingRunId: row.processing_run_id } }));
  res.json({ type: 'FeatureCollection', features, pagination: { total: count.rows[0].total, limit, offset }, spatialReference: 'EPSG:4326', dataStatus: features.length ? 'available' : 'not_ingested' });
});

const getFloodReferenceGeoJson = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const values = [];
  const predicates = [];
  if (req.query.eventKey) { values.push(String(req.query.eventKey)); predicates.push(`event_key=$${values.length}`); }
  if (req.query.bbox) {
    const filter = bboxFilter(req.query.bbox, values.length + 1);
    values.push(...filter.params);
    const first = values.length - 3;
    predicates.push(`ST_Intersects(geom, ST_MakeEnvelope($${first},$${first + 1},$${first + 2},$${first + 3},4326))`);
  }
  const where = predicates.length ? `WHERE ${predicates.join(' AND ')}` : '';
  const count = await db.query(`SELECT count(*)::int AS total FROM flood_reference_features ${where}`, values);
  const rows = await db.query(`SELECT id,dataset_key,source_feature_id,event_key,event_date,source_properties,event_metadata,processing_run_id,ST_Area(geom::geography)::double precision AS measured_geometry_area_m2,ST_AsGeoJSON(geom)::json AS geometry FROM flood_reference_features ${where} ORDER BY event_date,id LIMIT $${values.length + 1} OFFSET $${values.length + 2}`, [...values, limit, offset]);
  const features = rows.rows.map((row) => ({ type: 'Feature', id: row.id, geometry: row.geometry, properties: { evidenceKind: 'reference_observation', eventKey: row.event_key, eventDate: row.event_date, datasetKey: row.dataset_key, sourceFeatureId: row.source_feature_id, measuredGeometryAreaM2: row.measured_geometry_area_m2, eventMetadata: parseJson(row.event_metadata, {}), sourceProperties: parseJson(row.source_properties, {}), processingRunId: row.processing_run_id, limitations: 'Reported event-level area/population are retained separately from area measured from this source polygon.' } }));
  res.json({ type: 'FeatureCollection', features, pagination: { total: count.rows[0].total, limit, offset }, spatialReference: 'EPSG:4326', evidenceKind: 'reference_observation', dataStatus: features.length ? 'available' : 'not_ingested' });
});

const getMapOutputGeoJson = asyncRoute(async (req, res) => {
  const definition = mapLayerSql[req.params.layer];
  if (!definition) throw new AppError('UNKNOWN_LAYER', 'Map output layer is not registered', 404);
  const { limit, offset } = pagination(req.query);
  const filter = bboxFilter(req.query.bbox, 1);
  const values = filter.params;
  const where = `WHERE geom IS NOT NULL${filter.sql}`;
  const count = await db.query(`SELECT count(*)::int AS total FROM (${definition}) AS map_layer ${where}`, values);
  const rows = await db.query(`SELECT id,properties,ST_AsGeoJSON(geom)::json AS geometry FROM (${definition}) AS map_layer ${where} ORDER BY id LIMIT $${values.length + 1} OFFSET $${values.length + 2}`, [...values, limit, offset]);
  const features = rows.rows.map((row) => ({ type: 'Feature', id: row.id, geometry: row.geometry, properties: parseJson(row.properties, {}) }));
  res.json({ type: 'FeatureCollection', features, count: features.length, pagination: { total: count.rows[0].total, limit, offset }, spatialReference: 'EPSG:4326', layer: req.params.layer, status: features.length ? 'available' : 'not_assessed' });
});

const getWindResourceManifest = asyncRoute(async (_req, res) => {
  const manifestPath = path.join(windCacheDir, 'manifest.json');
  if (!fs.existsSync(manifestPath)) return res.json({ status: 'not_cached', products: Object.keys(windProducts).map((key) => ({ id: key, ...windProducts[key] })), syncCommand: 'npm run oseas:wind:sync' });
  const manifest = JSON.parse(await fs.promises.readFile(manifestPath, 'utf8'));
  res.json({ status: 'cached', manifest, mapLayers: Object.keys(windProducts).map((key) => ({ id: key, unit: windProducts[key].unit, url: `/api/v1/oseas/layers/wind_resource/${key}/geotiff`, mediaType: 'image/tiff' })) });
});

const downloadWindResource = asyncRoute(async (req, res, next) => {
  const product = windProducts[req.params.product];
  if (!product) throw new AppError('INVALID_PRODUCT', 'Unknown Global Wind Atlas product', 404);
  const file = path.join(windCacheDir, product.file);
  if (!fs.existsSync(file)) throw new AppError('NOT_CACHED', 'Wind resource raster is not cached; run npm run oseas:wind:sync', 404);
  res.type('image/tiff');
  res.set('Content-Disposition', `inline; filename="${product.file}"`);
  return res.sendFile(file, (error) => { if (error && !res.headersSent) next(error); });
});

const listAssets = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const values = [];
  const filters = [];
  if (req.query.type) { values.push(String(req.query.type)); filters.push(`a.asset_type=$${values.length}`); }
  if (req.query.wardId || req.query.countyId) {
    const level = req.query.wardId ? 'ward' : 'county';
    const unitId = req.query.wardId || req.query.countyId;
    validateUuid(unitId, `${level}Id`);
    values.push(level, unitId);
    filters.push(`EXISTS (SELECT 1 FROM asset_admin_assignments rel WHERE rel.energy_asset_id=a.id AND rel.unit_level=$${values.length - 1} AND rel.administrative_unit_id=$${values.length} AND rel.is_current=TRUE)`);
  }
  if (req.query.bbox) {
    const box = bboxFilter(req.query.bbox, values.length + 1);
    filters.push(box.sql);
    values.push(...box.params);
  }
  const where = filters.length ? `WHERE ${filters.join(' AND ')}` : '';
  const count = await db.query(`SELECT count(*)::int AS total FROM energy_assets a ${where}`, values);
  values.push(limit, offset);
  const rows = await db.query(`
    SELECT a.id,a.asset_type,a.name,a.voltage_kv,a.source_dataset_key,a.source_asset_id,a.source_feature_id,a.source_properties,
           ST_AsGeoJSON(a.geom)::json AS geometry
    FROM energy_assets a ${where} ORDER BY a.asset_type,a.id LIMIT $${values.length - 1} OFFSET $${values.length}
  `, values);
  res.json({ type: 'FeatureCollection', features: rows.rows.map((row) => ({ type: 'Feature', id: row.id, geometry: row.geometry, properties: { assetType: row.asset_type, name: row.name, voltageKv: row.voltage_kv, sourceDataset: row.source_dataset_key, sourceFeatureId: row.source_feature_id, sourceProperties: parseJson(row.source_properties, {}) } })), pagination: { total: count.rows[0].total, limit, offset }, spatialReference: 'EPSG:4326' });
});

const getAssetExposure = asyncRoute(async (req, res) => {
  validateUuid(req.params.id);
  const result = await db.query(`SELECT id,hazard_type,hazard_event_id,assessment_period_start,assessment_period_end,exposure_status,intersection_area_m2,intersection_length_m,distance_m,evidence_kind,confidence,provenance,processing_run_id,created_at FROM asset_hazard_exposure WHERE energy_asset_id=$1 ORDER BY created_at DESC`, [req.params.id]);
  res.json({ assetId: req.params.id, status: result.rows.length ? 'assessed' : 'not_assessed', data: result.rows.map((row) => ({ ...row, provenance: parseJson(row.provenance, {}) })) });
});

const getAssetVulnerability = asyncRoute(async (req, res) => {
  validateUuid(req.params.id);
  const result = await db.query('SELECT * FROM asset_vulnerability_assessments WHERE energy_asset_id=$1 ORDER BY created_at DESC', [req.params.id]);
  res.json({ assetId: req.params.id, status: result.rows.length ? result.rows[0].status : 'not_assessed', data: result.rows });
});

const getAdminSummary = asyncRoute(async (req, res) => {
  const { level, id } = req.params;
  if (!['ward', 'county'].includes(level)) throw new AppError('INVALID_LEVEL', 'level must be ward or county', 400);
  validateUuid(id);
  const result = await db.query(`
    SELECT u.id,u.unit_level,u.name,u.stable_code,s.hazard_type,s.event_fingerprint,s.period_start,s.period_end,
           s.assessment_status,s.assigned_energy_asset_count,s.candidate_exposed_asset_count,
           s.candidate_exposure_fraction,s.provenance,s.processing_run_id,ST_AsGeoJSON(u.geom)::json AS geometry
    FROM administrative_units u LEFT JOIN administrative_hazard_summaries s ON s.administrative_unit_id=u.id
    WHERE u.id=$1 AND u.unit_level=$2 ORDER BY s.period_end DESC NULLS LAST LIMIT 1
  `, [id, level]);
  if (!result.rows.length) throw new AppError('NOT_FOUND', `${level} boundary was not found`, 404);
  const row = result.rows[0];
  res.json({ type: 'Feature', id: row.id, geometry: row.geometry, properties: { level: row.unit_level, name: row.name, stableCode: row.stable_code, hazardType: row.hazard_type, eventFingerprint: row.event_fingerprint, periodStart: row.period_start, periodEnd: row.period_end, assessmentStatus: row.assessment_status || 'not_assessed', assignedEnergyAssetCount: row.assigned_energy_asset_count, candidateExposedAssetCount: row.candidate_exposed_asset_count, candidateExposureFraction: row.candidate_exposure_fraction, provenance: parseJson(row.provenance, {}) }, spatialReference: 'EPSG:4326' });
});

const getPriorities = asyncRoute(async (req, res) => {
  const { limit, offset } = pagination(req.query);
  const result = await db.query(`SELECT id,energy_asset_id,action,priority,status,reason,evidence,assumptions,confidence,created_at FROM intervention_scenarios WHERE status IN ('candidate','reviewed') ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,created_at DESC LIMIT $1 OFFSET $2`, [limit, offset]);
  res.json({ data: result.rows.map((row) => ({ ...row, evidence: parseJson(row.evidence, {}), assumptions: parseJson(row.assumptions, {}) })), pagination: { limit, offset }, status: result.rows.length ? 'available' : 'not_assessed' });
});

module.exports = { getReadiness, getCatalog, getRuns, getRun, getLayers, getFloodGeoJson, getHydrographyGeoJson, getFloodReferenceGeoJson, getMapOutputGeoJson, getWindResourceManifest, downloadWindResource, listAssets, getAssetExposure, getAssetVulnerability, getAdminSummary, getPriorities };
