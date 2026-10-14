'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const app = require('../../src/app');
const { buildAssetListFilter, buildMapOutputFilter, mapAssetExposureRows, mapAssetVulnerabilityRows } = require('../../src/controllers/oseasController');

test('root metadata identifies OSEAS and exposes integration readiness route', async () => {
  const response = await request(app).get('/');
  assert.equal(response.status, 200);
  assert.equal(response.body.service, 'oseas-climate-risk-api');
  assert.equal(response.body.endpoints.oseas.readiness, '/api/v1/oseas/readiness');
  assert.equal(response.body.endpoints.oseas.asset_vulnerability, '/api/v1/oseas/assets/{id}/vulnerability');
  assert.equal(response.body.endpoints.oseas.vulnerability_layer, '/api/v1/oseas/layers/asset_vulnerability/geojson');
  assert.doesNotMatch(JSON.stringify(response.body), /Kilimani/i);
});

test('asset exposure route rejects invalid UUID without a database call', async () => {
  const response = await request(app).get('/api/v1/oseas/assets/not-a-uuid/exposure');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_ID');
});

test('asset criticality route rejects invalid UUID without a database call', async () => {
  const response = await request(app).get('/api/v1/oseas/assets/not-a-uuid/criticality');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_ID');
});

test('asset vulnerability route requested for the pilot rejects invalid UUID without a database call', async () => {
  const response = await request(app).get('/api/v1/oseas/assets/not-a-uuid/vulnerability');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_ID');
});

test('asset service-dependency route rejects invalid UUID without a database call', async () => {
  const response = await request(app).get('/api/v1/oseas/assets/not-a-uuid/service-dependencies');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_ID');
});

test('administrative route rejects unsupported boundary level', async () => {
  const response = await request(app).get('/api/v1/oseas/administrative/subcounty/00000000-0000-4000-8000-000000000001/summary');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_LEVEL');
});

test('flood map route validates bbox before querying persisted results', async () => {
  const response = await request(app).get('/api/v1/oseas/layers/flood_candidate/geojson?bbox=invalid');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_BBOX');
});

test('rainfall map route is registered and validates bbox before querying persisted results', async () => {
  const response = await request(app).get('/api/v1/oseas/layers/rainfall/geojson?bbox=invalid');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_BBOX');
});

test('asset bbox-only filter builds a valid WHERE predicate and four bound coordinates', () => {
  const filter = buildAssetListFilter({ bbox: '34.6,-0.4,35.3,0.1' });
  assert.match(filter.where, /^WHERE ST_Intersects\(geom,/);
  assert.doesNotMatch(filter.where, /WHERE\s+AND/i);
  assert.deepEqual(filter.values, [34.6, -0.4, 35.3, 0.1]);
});

test('asset source dataset and bbox filters can isolate the Kano pilot with parameterized SQL', () => {
  const filter = buildAssetListFilter({ sourceDataset: 'osm_kano_pilot', bbox: '34.6,-0.4,35.3,0.1' });
  assert.match(filter.where, /a\.source_dataset_key=\$1/);
  assert.match(filter.where, /ST_Intersects\(geom, ST_MakeEnvelope\(\$2,\$3,\$4,\$5,4326\)\)/);
  assert.deepEqual(filter.values, ['osm_kano_pilot', 34.6, -0.4, 35.3, 0.1]);
});

test('asset source dataset filter rejects malformed identifiers', () => {
  assert.throws(() => buildAssetListFilter({ sourceDataset: "pilot' OR 1=1" }), { code: 'INVALID_SOURCE_DATASET' });
});

test('vulnerability map layer supports a parameterized pilot source filter with bbox', () => {
  const filter = buildMapOutputFilter('asset_vulnerability', { sourceDataset: 'osm_kano_pilot', bbox: '34.6,-0.4,35.3,0.1' });
  assert.match(filter.where, /^WHERE geom IS NOT NULL AND properties->>'sourceDataset'=\$1 AND ST_Intersects\(geom,/);
  assert.doesNotMatch(filter.where, /WHERE\s+AND/i);
  assert.deepEqual(filter.values, ['osm_kano_pilot', 34.6, -0.4, 35.3, 0.1]);
});

test('source dataset map filter is rejected for layers without asset source metadata', () => {
  assert.throws(() => buildMapOutputFilter('nightlights', { sourceDataset: 'osm_kano_pilot' }), { code: 'UNSUPPORTED_FILTER' });
});

test('asset exposure maps pilot score explicitly and preserves not-assessed hazards', () => {
  const data = mapAssetExposureRows([
    { hazard_type: 'flood', exposure_status: 'exposed', provenance: { pilot: 'kano_plains', exposure: 0.6 } },
    { hazard_type: 'heat', exposure_status: 'not_assessed', provenance: { pilot: 'kano_plains', exposure: null } },
  ]);
  assert.equal(data[0].exposureScore, 0.6);
  assert.equal(data[0].exposureScoreStatus, 'pilot_screening');
  assert.equal(data[0].scoringScope, 'kano_plains');
  assert.equal(data[1].exposureScore, null);
  assert.equal(data[1].exposureScoreStatus, 'not_assessed');
});

test('asset vulnerability maps the teammate pilot score with scope and preserves withheld status', () => {
  const data = mapAssetVulnerabilityRows([
    { status: 'assessed', score: 0.48, provenance: { pilot: 'kano_plains' } },
    { status: 'unknown', score: null, provenance: {} },
  ]);
  assert.equal(data[0].score, 0.48);
  assert.equal(data[0].scoreStatus, 'pilot_screening');
  assert.equal(data[0].scoringScope, 'kano_plains');
  assert.equal(data[1].score, null);
  assert.equal(data[1].scoreStatus, 'withheld');
});

test('population exposure layer validates reporting-unit UUID before querying persisted results', async () => {
  const response = await request(app).get('/api/v1/oseas/layers/population_exposure/geojson?reportingUnitId=bad');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_ID');
});

test('population exposure layer rejects unsupported assessment statuses', async () => {
  const response = await request(app).get('/api/v1/oseas/layers/population_exposure/geojson?status=excellent');
  assert.equal(response.status, 400);
  assert.equal(response.body.error.code, 'INVALID_STATUS');
});

test('unknown map output layer is rejected before any database query', async () => {
  const response = await request(app).get('/api/v1/oseas/layers/not_a_real_layer/geojson');
  assert.equal(response.status, 404);
  assert.equal(response.body.error.code, 'UNKNOWN_LAYER');
});

test('source dataset map filter rejects malformed identifiers', () => {
  assert.throws(() => buildMapOutputFilter('asset_vulnerability', { sourceDataset: "pilot' OR 1=1" }), { code: 'INVALID_SOURCE_DATASET' });
});
