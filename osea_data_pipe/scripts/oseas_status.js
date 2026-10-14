"use strict";

// Read-only status for the latest OSEAS ingestion run and rows stamped by it.
require("dotenv").config({ quiet: true });
const db = require("../src/repositories/db");

async function main() {
  try {
    const runs = await db.query(`
      SELECT id, status, started_at, finished_at, metadata
      FROM ingestion_runs
      WHERE pipeline_name = 'oseas_earth_engine_ingest'
      ORDER BY started_at DESC LIMIT 5
    `);
    const latest = runs.rows[0] || null;
    let counts = [];
    let quality = [];
    let duplicateSourceKeys = [];
    let sourceUniquenessConstraints = [];
    let importerSessions = [];
    if (latest) {
      const countResult = await db.query(`
        SELECT source_dataset_key, entity_type, count(*)::bigint AS rows
        FROM (
          SELECT source_dataset_key, 'energy_asset'::text AS entity_type FROM energy_assets WHERE last_ingested_run_id = $1
          UNION ALL
          SELECT source_dataset_key, 'administrative_unit'::text FROM administrative_units WHERE last_ingested_run_id = $1
          UNION ALL
          SELECT source_dataset_key, 'critical_service'::text FROM critical_services WHERE last_ingested_run_id = $1
        ) records
        GROUP BY source_dataset_key, entity_type
        ORDER BY source_dataset_key, entity_type
      `, [latest.id]);
      counts = countResult.rows;
      const qualityResult = await db.query(`
        SELECT dataset_key, check_name, status, checked_at, details
        FROM data_quality_checks WHERE run_id = $1 ORDER BY checked_at DESC
      `, [latest.id]);
      quality = qualityResult.rows;
    }
    const duplicates = await db.query(`
      SELECT entity_type, source_dataset_key, source_feature_id, count(*)::int AS duplicate_rows
      FROM (
        SELECT 'energy_asset'::text AS entity_type, source_dataset_key, source_feature_id FROM energy_assets
        UNION ALL
        SELECT 'administrative_unit', source_dataset_key, source_feature_id FROM administrative_units
        UNION ALL
        SELECT 'critical_service', source_dataset_key, source_feature_id FROM critical_services
      ) records
      GROUP BY entity_type, source_dataset_key, source_feature_id
      HAVING count(*) > 1
      ORDER BY entity_type, source_dataset_key
      LIMIT 50
    `);
    duplicateSourceKeys = duplicates.rows;
    const constraints = await db.query(`
      SELECT conrelid::regclass::text AS table_name, conname AS constraint_name
      FROM pg_constraint
      WHERE contype IN ('u','p')
        AND conrelid IN ('energy_assets'::regclass, 'administrative_units'::regclass, 'critical_services'::regclass)
      ORDER BY table_name, constraint_name
    `);
    sourceUniquenessConstraints = constraints.rows;
    const sessions = await db.query(`
      SELECT application_name, state, query_start, wait_event_type, wait_event,
             CASE WHEN state = 'active' THEN left(query, 180) ELSE NULL END AS current_query
      FROM pg_stat_activity
      WHERE application_name = 'oseas-ingest' AND pid <> pg_backend_pid()
      ORDER BY query_start
    `);
    importerSessions = sessions.rows;
    console.log(JSON.stringify({ latestRun: latest, recentRuns: runs.rows, rowsWrittenByLatestRun: counts, qualityChecks: quality, duplicateSourceKeys, sourceUniquenessConstraints, importerSessions }, null, 2));
  } finally {
    await db.closePool();
  }
}

main().catch((error) => {
  console.error(`Read-only ingestion status failed: ${error.message}`);
  process.exitCode = 1;
});
