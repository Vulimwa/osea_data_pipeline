'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const db = require('../../src/repositories/db');
const healthController = require('../../src/health/healthController');

async function callReady() {
  let statusCode = 200;
  let body;
  await healthController.getReady({}, {
    status(code) { statusCode = code; return this; },
    json(value) { body = value; return this; },
  });
  return { statusCode, body };
}

test('readiness exposes only sanitized database state when the database is unavailable', async () => {
  const originalCheckHealth = db.checkHealth;
  db.checkHealth = async () => ({ status: 'error', connected: false, message: 'private host and credentials' });
  try {
    const response = await callReady();
    assert.equal(response.statusCode, 503);
    assert.deepEqual(response.body.checks, { database: 'unavailable' });
    assert.doesNotMatch(JSON.stringify(response.body), /private host|credentials|earth_engine/i);
  } finally {
    db.checkHealth = originalCheckHealth;
  }
});

test('readiness reports ready when PostGIS responds without exposing database details', async () => {
  const originalCheckHealth = db.checkHealth;
  db.checkHealth = async () => ({ status: 'ok', connected: true, postgis_version: 'private version detail' });
  try {
    const response = await callReady();
    assert.equal(response.statusCode, 200);
    assert.deepEqual(response.body.checks, { database: 'ok' });
    assert.doesNotMatch(JSON.stringify(response.body), /private version detail/);
  } finally {
    db.checkHealth = originalCheckHealth;
  }
});
