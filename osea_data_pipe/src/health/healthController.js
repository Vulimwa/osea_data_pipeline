'use strict';

const fs = require('fs');
const path = require('path');
const db = require('../repositories/db');
const config = require('../config');

function getGeeStatus() {
  const keyPath = config.GEE_SERVICE_ACCOUNT_KEY_PATH;
  const resolvedKey =
    keyPath && fs.existsSync(path.resolve(process.cwd(), keyPath)) ? keyPath : null;

  return {
    configured: Boolean(config.GEE_PROJECT_ID),
    serviceCredentialsConfigured: Boolean(resolvedKey && config.GEE_SERVICE_ACCOUNT_EMAIL),
    liveConnection: 'not_checked_by_health_probe',
  };
}

function getHealth(req, res) {
  res.json({
    status: 'ok',
    service: 'oseas-climate-risk-api',
    version: config.PROCESSING_VERSION,
    timestamp: new Date().toISOString(),
    uptime_seconds: Math.floor(process.uptime()),
  });
}

function getLive(req, res) {
  res.json({
    status: 'live',
    timestamp: new Date().toISOString(),
  });
}

async function getReady(req, res) {
  const dbHealth = await db.checkHealth();
  const gee = getGeeStatus();
  const isDatabaseReady = dbHealth.connected === true;
  const readinessStatus = isDatabaseReady ? 'ready_with_limitations' : 'blocked';
  const statusCode = isDatabaseReady ? 200 : 503;

  res.status(statusCode).json({
    status: readinessStatus,
    checks: {
      configuration: 'ok',
      database: dbHealth,
      earth_engine: gee,
      hazard_products: 'Use /api/v1/oseas/readiness for processing and output status',
    },
    timestamp: new Date().toISOString(),
  });
}

module.exports = {
  getHealth,
  getLive,
  getReady,
};
