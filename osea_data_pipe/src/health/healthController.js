'use strict';

const db = require('../repositories/db');
const config = require('../config');

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
  const isDatabaseReady = dbHealth.connected === true;
  const readinessStatus = isDatabaseReady ? 'ready' : 'unavailable';
  const statusCode = isDatabaseReady ? 200 : 503;

  res.status(statusCode).json({
    status: readinessStatus,
    checks: {
      database: isDatabaseReady ? 'ok' : 'unavailable',
    },
    timestamp: new Date().toISOString(),
  });
}

module.exports = {
  getHealth,
  getLive,
  getReady,
};
