'use strict';

const config = require('../config');
const { AppError } = require('./errorHandler');

function isRequired(settings = config) {
  return settings.NODE_ENV === 'production' || settings.OSEAS_REQUIRE_AUTH === true;
}

async function supabaseBearerAuth(req, _res, next) {
  if (!isRequired()) return next();
  const authorization = req.headers.authorization || '';
  const match = authorization.match(/^Bearer\s+([^\s]+)$/i);
  if (!match) return next(new AppError('AUTH_REQUIRED', 'A valid Supabase access token is required', 401));
  if (!config.SUPABASE_URL || !config.SUPABASE_SERVICE_ROLE_KEY) {
    return next(new AppError('AUTH_NOT_CONFIGURED', 'Supabase token verification is not configured', 503));
  }
  try {
    const response = await fetch(`${config.SUPABASE_URL.replace(/\/$/, '')}/auth/v1/user`, {
      method: 'GET',
      headers: {
        apikey: config.SUPABASE_SERVICE_ROLE_KEY,
        authorization: `Bearer ${match[1]}`,
        accept: 'application/json',
      },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return next(new AppError('AUTH_INVALID', 'Supabase rejected the access token', 401));
    const user = await response.json();
    if (!user || typeof user.id !== 'string') return next(new AppError('AUTH_INVALID', 'Supabase returned an invalid user identity', 401));
    req.user = { id: user.id, role: user.app_metadata?.role || 'authenticated' };
    return next();
  } catch (_error) {
    return next(new AppError('AUTH_PROVIDER_UNAVAILABLE', 'Supabase token verification is unavailable', 503));
  }
}

module.exports = { supabaseBearerAuth, isRequired };
