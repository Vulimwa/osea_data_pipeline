/**
 * OSEAS API configuration.
 */
"use strict";

const dotenv = require("dotenv");
const { z } = require("zod");
const path = require("path");

// Load .env then .env.local (local overrides; never commit either)
dotenv.config();
dotenv.config({ path: path.resolve(__dirname, "../../.env.local"), override: true });

// Define configuration validation schema
const configSchema = z.object({
  // Runtime
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),
  PORT: z.coerce.number().default(3000),
  HOST: z.string().default("0.0.0.0"),
  API_VERSION: z.string().default("v1"),
  CORS_ORIGIN: z.string().default("*"),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),

  // Rate limiting
  RATE_LIMIT_WINDOW_MS: z.coerce.number().default(15 * 60 * 1000),
  RATE_LIMIT_MAX: z.coerce.number().default(500),

  // Database
  DB_URL: z.string().optional(),
  DATABASE_URL: z.string().optional(),
  SUPABASE_DB_URL: z.string().optional(),
  SUPABASE_URL: z.string().url().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().optional(),
  OSEAS_REQUIRE_AUTH: z.union([
    z.boolean(),
    z.enum(["true", "false"]).transform((value) => value === "true"),
  ]).default(false),
  DB_POOL_MIN: z.coerce.number().default(2),
  DB_POOL_MAX: z.coerce.number().default(10),
  DB_TIMEOUT_MS: z.coerce.number().default(10000),

  // Earth Engine readiness metadata
  GEE_PROJECT_ID: z.string().optional(),
  GEE_SERVICE_ACCOUNT_EMAIL: z.string().optional(),
  GEE_SERVICE_ACCOUNT_KEY_PATH: z.string().optional(),

  PROCESSING_VERSION: z.string().default("v1.0.0"),
});

// Parse and validate configuration
let parsedConfig;
try {
  parsedConfig = configSchema.parse(process.env);
} catch (error) {
  if (error instanceof z.ZodError) {
    const errorDetails = error.errors
      .map((err) => ` - ${err.path.join(".")}: ${err.message}`)
      .join("\n");
    console.error("\n========================================================");
    console.error(
      "CRITICAL CONFIGURATION ERROR: Invalid environment variables",
    );
    console.error(errorDetails);
    console.error("========================================================\n");
    throw new Error(`Configuration validation failed:\n${errorDetails}`);
  }
  throw error;
}

module.exports = Object.freeze(parsedConfig);
