#!/usr/bin/env node
"use strict";

// The schema is intentionally applied by the operator in Supabase SQL Editor.
// This command only checks connectivity and reports whether OSEAS tables exist.
require("dotenv").config();
const db = require("../src/repositories/db");

async function main() {
  const health = await db.checkHealth();
  if (!health.connected) {
    throw new Error(`PostGIS database is not ready: ${health.message || health.status}`);
  }
  const result = await db.query(`
    SELECT table_name, column_name FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = ANY($1::text[])
  `, [["datasets", "ingestion_runs", "dataset_versions", "data_quality_checks", "energy_assets", "network_lines", "substations", "distribution_transformers", "power_stations", "mini_grids", "critical_services", "service_dependencies", "administrative_units", "asset_admin_assignments", "climate_observations", "climate_projections", "hazard_events", "flood_extents", "fire_events", "terrain_metrics", "land_cover_metrics", "model_runs", "asset_hazard_exposure", "asset_vulnerability_assessments", "asset_criticality_assessments", "service_dependency_assessments", "ward_vulnerability_summary", "county_vulnerability_summary", "administrative_hazard_summaries", "prithvi_national_batches", "prithvi_national_admin_batch_stats", "intervention_scenarios", "assessment_provenance", "hydrography_features", "flood_reference_features", "spatial_coverage_assessments", "population_exposure_assessments", "grid_resilience_assessments"]]);
  const columns = new Map();
  for (const row of result.rows) {
    if (!columns.has(row.table_name)) columns.set(row.table_name, new Set());
    columns.get(row.table_name).add(row.column_name);
  }
  const required = {
    datasets: ["dataset_key", "source_reference", "last_ingested_at"],
    ingestion_runs: ["id", "pipeline_name", "status", "started_at", "finished_at", "metadata"],
    dataset_versions: ["dataset_key", "source_reference", "retrieved_at", "feature_count", "metadata"],
    data_quality_checks: ["run_id", "dataset_key", "check_name", "status", "details"],
    energy_assets: ["id", "asset_type", "source_dataset_key", "source_asset_id", "source_feature_id", "source_properties", "geom", "last_ingested_run_id"],
    network_lines: ["asset_id", "voltage_kv", "line_class"],
    substations: ["asset_id", "source_properties"],
    distribution_transformers: ["asset_id", "source_properties"],
    power_stations: ["asset_id", "source_properties"],
    mini_grids: ["asset_id", "development_status", "source_properties"],
    critical_services: ["id", "service_type", "source_dataset_key", "source_asset_id", "source_feature_id", "source_properties", "geom", "last_ingested_run_id"],
    administrative_units: ["id", "unit_level", "source_dataset_key", "source_asset_id", "source_feature_id", "stable_code", "source_properties", "geom", "last_ingested_run_id"],
    asset_admin_assignments: ["id", "energy_asset_id", "administrative_unit_id", "unit_level", "relation_method", "intersection_length_m", "is_current"],
    hazard_events: ["id", "hazard_type", "evidence_kind", "dataset_key", "event_start", "event_end", "geom", "metadata", "processing_run_id"],
    flood_extents: ["hazard_event_id", "observation_start", "observation_end", "method", "area_km2", "quality"],
    asset_hazard_exposure: ["id", "energy_asset_id", "hazard_event_id", "hazard_type", "exposure_status", "evidence_kind", "provenance", "processing_run_id"],
    model_runs: ["id", "model_name", "model_version", "task", "parameters", "metrics", "status", "processing_run_id"],
    administrative_hazard_summaries: ["id", "administrative_unit_id", "hazard_type", "event_fingerprint", "assessment_status", "candidate_exposed_asset_count", "provenance", "processing_run_id", "total_pixels", "valid_pixels", "candidate_pixels", "candidate_area_m2", "valid_coverage_fraction"],
    prithvi_national_batches: ["event_fingerprint", "batch_id", "grid_x", "grid_y", "batch_geom", "status", "scene_ids", "valid_pixels", "candidate_pixels", "candidate_area_m2"],
    prithvi_national_admin_batch_stats: ["event_fingerprint", "batch_id", "administrative_unit_id", "total_pixels", "valid_pixels", "candidate_pixels"],
    hydrography_features: ["id", "dataset_key", "source_feature_id", "feature_type", "source_properties", "geom", "processing_run_id"],
    flood_reference_features: ["id", "dataset_key", "source_feature_id", "event_key", "event_date", "source_properties", "event_metadata", "geom", "processing_run_id"],
    spatial_coverage_assessments: ["id", "coverage_status", "area_coverage_fraction", "valid_data_fraction", "observation_footprint", "valid_data_footprint", "validation_status", "provenance"],
    population_exposure_assessments: ["id", "dataset_key", "hazard_event_id", "reporting_unit_id", "population_total", "population_potentially_exposed", "assessment_status", "method", "evidence", "geom", "processing_run_id"],
    grid_resilience_assessments: ["id", "assessment_status", "score", "criteria", "geom", "processing_run_id"],
    service_dependencies: ["energy_asset_id", "critical_service_id", "evidence_dataset_key", "evidence", "confidence", "verified"],
    service_dependency_assessments: ["energy_asset_id", "critical_service_id", "status", "evidence", "confidence", "processing_run_id"],
    asset_vulnerability_assessments: ["energy_asset_id", "status", "vulnerability_class", "score", "sensitivity", "adaptive_capacity", "missing_evidence", "provenance"],
    asset_criticality_assessments: ["energy_asset_id", "status", "score", "method", "evidence", "confidence"],
    ward_vulnerability_summary: ["ward_id", "assessment_run_id", "summary_status", "asset_counts", "hazard_counts", "provenance"],
    county_vulnerability_summary: ["county_id", "assessment_run_id", "summary_status", "asset_counts", "hazard_counts", "provenance"],
    intervention_scenarios: ["id", "energy_asset_id", "action", "status", "reason", "evidence", "assumptions", "processing_run_id"],
    assessment_provenance: ["assessment_table", "assessment_id", "dataset_key", "dataset_version_id", "model_run_id", "parameters"],
  };
  const missing = [];
  for (const [table, requiredColumns] of Object.entries(required)) {
    const existing = columns.get(table);
    if (!existing) missing.push(`${table} (table)`);
    else for (const column of requiredColumns) if (!existing.has(column)) missing.push(`${table}.${column}`);
  }
  console.log(`Database connected; PostGIS ${health.postgis_version || "available"}.`);
  if (missing.length) {
    console.error(`OSEAS schema is missing required objects or columns. Review and apply database/schema.sql in Supabase SQL Editor. Missing: ${missing.join(", ")}`);
    process.exitCode = 1;
  } else {
    console.log("OSEAS core schema is installed.");
  }
  await db.closePool();
}

main().catch(async (error) => {
  console.error(`Database check failed: ${error.message}`);
  await db.closePool();
  process.exitCode = 1;
});
