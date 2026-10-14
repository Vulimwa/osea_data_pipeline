/** OSEAS Express API. */
"use strict";

const express = require("express");
const cors = require("cors");
const helmet = require("helmet");
const rateLimit = require("express-rate-limit");
const config = require("./config");
const requestIdMiddleware = require("./middleware/requestId");
const requestLoggerMiddleware = require("./middleware/logger");
const {
  errorHandlerMiddleware,
  AppError,
} = require("./middleware/errorHandler");
const healthController = require("./health/healthController");
const v1Router = require("./routes");

const app = express();

// 1. Security Headers via Helmet
app.use(
  helmet({
    contentSecurityPolicy: false,
    crossOriginResourcePolicy: { policy: "cross-origin" },
  }),
);

// 2. CORS Configuration
app.use(
  cors({
    origin: config.CORS_ORIGIN === '*' ? true : config.CORS_ORIGIN.split(','),
    methods: ['GET', 'POST', 'PATCH', 'OPTIONS'],
    allowedHeaders: [
      'Content-Type',
      'Authorization',
      'X-Request-ID',
      'X-User-Role',
      'X-User-Id',
      'X-User-Name',
    ],
    credentials: true,
  }),
);

// 3. Rate Limiting
const limiter = rateLimit({
  windowMs: config.RATE_LIMIT_WINDOW_MS,
  max: config.RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: {
      code: "RATE_LIMIT_EXCEEDED",
      message: "Too many requests, please try again later",
      details: {},
    },
  },
});
app.use(limiter);

// 4. Request parsing
app.use(express.json({ limit: "10mb" }));
app.use(express.urlencoded({ extended: true, limit: "10mb" }));

// 5. Request Correlation ID & Logging
app.use(requestIdMiddleware);
app.use(requestLoggerMiddleware);

// 6. Health & Liveness / Readiness Probes (Root level)
app.get("/health", healthController.getHealth);
app.get("/health/live", healthController.getLive);
app.get("/health/ready", healthController.getReady);

// 7. OSEAS API service index (/ and /api)
const getEngineInfo = (req, res) => {
  res.json({
    service: "oseas-climate-risk-api",
    description: "Kenya energy infrastructure and climate hazard evidence API.",
    status: "available; see readiness checks before use",
    pipeline:
      "Earth Engine source ingestion -> PostGIS -> bounded hazard assessment -> GeoJSON API",
    endpoints: {
      health: "/health",
      oseas: {
        readiness: "/api/v1/oseas/readiness",
        catalog: "/api/v1/oseas/catalog",
        assets: "/api/v1/oseas/assets",
        flood_candidates: "/api/v1/oseas/layers/flood_candidate/geojson",
        flood_reference: "/api/v1/oseas/layers/flood_reference/geojson",
        hydrography: "/api/v1/oseas/layers/hydrography/geojson",
        wind_resource: "/api/v1/oseas/layers/wind_resource",
      },
    },
  });
};

app.get("/", getEngineInfo);
app.get("/api", getEngineInfo);

// 8. Mount Versioned REST API under /api/v1
app.use("/api/v1", v1Router);

// 9. Catch-All 404 Handler for API routes only
app.use("/api", (req, res, next) => {
  next(
    new AppError("NOT_FOUND", `Cannot ${req.method} ${req.originalUrl}`, 404),
  );
});

// 10. Centralized Global Error Handler
app.use(errorHandlerMiddleware);

module.exports = app;
