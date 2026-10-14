'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const app = require('../../src/app');

test('root metadata identifies OSEAS and exposes integration readiness route', async () => {
  const response = await request(app).get('/');
  assert.equal(response.status, 200);
  assert.equal(response.body.service, 'oseas-climate-risk-api');
  assert.equal(response.body.endpoints.oseas.readiness, '/api/v1/oseas/readiness');
  assert.doesNotMatch(JSON.stringify(response.body), /Kilimani/i);
});

test('asset exposure route rejects invalid UUID without a database call', async () => {
  const response = await request(app).get('/api/v1/oseas/assets/not-a-uuid/exposure');
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
