'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { isRequired } = require('../../src/middleware/supabaseBearerAuth');

test('OSEAS bearer auth is mandatory in production', () => {
  assert.equal(isRequired({ NODE_ENV: 'production', OSEAS_REQUIRE_AUTH: false }), true);
});

test('OSEAS bearer auth can be enabled in development', () => {
  assert.equal(isRequired({ NODE_ENV: 'development', OSEAS_REQUIRE_AUTH: true }), true);
});

test('OSEAS bearer auth is optional in development by default', () => {
  assert.equal(isRequired({ NODE_ENV: 'development', OSEAS_REQUIRE_AUTH: false }), false);
});
