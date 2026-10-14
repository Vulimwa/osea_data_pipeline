"""Evidence-gated asset criticality, dependency, vulnerability and resilience outputs."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

METHOD_VERSION = "oseas_evidence_gated_assessments_v1"
ID_NAMESPACE = uuid.UUID("9ed30a7b-a31d-4f4d-a237-6f9155d8a1b0")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(table: str, asset_id: str, evidence: Any) -> uuid.UUID:
    digest = hashlib.sha256(_canonical(evidence).encode("utf-8")).hexdigest()
    return uuid.uuid5(ID_NAMESPACE, f"{METHOD_VERSION}|{table}|{asset_id}|{digest}")


def _system_class_counts(by_type: dict[str, int]) -> dict[str, int]:
    counts = {"centralizedGridNetworkAssets": 0, "decentralizedMiniGrids": 0,
              "distributionAssets": 0, "generationAssets": 0, "systemClassUnclassified": 0}
    for raw_type, asset_count in by_type.items():
        asset_type = raw_type.casefold()
        if "mini_grid" in asset_type or "minigrid" in asset_type:
            counts["decentralizedMiniGrids"] += asset_count
        elif "transformer" in asset_type or "distribution" in asset_type:
            counts["distributionAssets"] += asset_count
        elif asset_type in {"primary_substation", "substation", "transmission_line", "network_line"} or "transmission" in asset_type:
            counts["centralizedGridNetworkAssets"] += asset_count
        elif "power_station" in asset_type or "power_plant" in asset_type or "generator" in asset_type:
            counts["generationAssets"] += asset_count
        else:
            counts["systemClassUnclassified"] += asset_count
    return counts


def assess_assets(connection: Any, *, batch_size: int = 500,
                  connection_dsn: str | None = None) -> dict[str, int | str]:
    """Persist non-fabricated asset assessments, idempotent by input evidence hash.

    This deliberately withholds numeric criticality, vulnerability and resilience
    scores where the OSEAS inventory lacks validated topology, service load,
    sensitivity, redundancy, or operational evidence.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    run_id = None
    method = METHOD_VERSION
    session_started = time.monotonic()
    owns_connection = False
    counts = {"assets_processed": 0, "criticality_assessments": 0, "dependency_assessments": 0,
              "vulnerability_assessments": 0, "resilience_assessments": 0, "intervention_candidates": 0,
              "ward_vulnerability_summaries": 0, "county_vulnerability_summaries": 0}
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_evidence_gated_assessments",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another OSEAS evidence assessment run is active")
        cur.execute("""SELECT id FROM ingestion_runs WHERE pipeline_name='oseas_evidence_gated_assessments'
          AND status IN ('running','partial') AND metadata->>'method'=%s ORDER BY started_at DESC LIMIT 1""", (method,))
        previous = cur.fetchone()
        if previous:
            run_id = previous[0]
            cur.execute("""SELECT count(DISTINCT energy_asset_id),max(energy_asset_id::text)
              FROM asset_vulnerability_assessments WHERE processing_run_id=%s""", (run_id,))
            counts["assets_processed"], last_asset_id = cur.fetchone()
            for key, table in (("criticality_assessments", "asset_criticality_assessments"),
                               ("dependency_assessments", "service_dependency_assessments"),
                               ("vulnerability_assessments", "asset_vulnerability_assessments"),
                               ("resilience_assessments", "grid_resilience_assessments"),
                               ("intervention_candidates", "intervention_scenarios")):
                cur.execute(f"SELECT count(*) FROM {table} WHERE processing_run_id=%s", (run_id,))
                counts[key] = cur.fetchone()[0]
            last_asset_id = last_asset_id or "00000000-0000-0000-0000-000000000000"
            cur.execute("""UPDATE ingestion_runs SET status='running',finished_at=NULL,error_message=NULL,
              metadata=metadata||%s::jsonb WHERE id=%s""", (json.dumps({"batch_size": batch_size,
                "assets_processed": counts["assets_processed"], "last_asset_id": last_asset_id}), run_id))
        else:
            run_id = uuid.uuid4()
            last_asset_id = "00000000-0000-0000-0000-000000000000"
            cur.execute("INSERT INTO ingestion_runs (id,pipeline_name,status,metadata) VALUES (%s,'oseas_evidence_gated_assessments','running',%s::jsonb)",
                        (run_id, json.dumps({"method": method, "batch_size": batch_size})))
    connection.commit()
    try:
        assessment_started = time.monotonic()
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM energy_assets")
            total_assets = cur.fetchone()[0]
        resumed_assets = counts["assets_processed"]
        asset_query = """
              SELECT a.id::text,a.asset_type,a.name,a.voltage_kv,a.source_properties,
                     ST_AsGeoJSON(a.geom) AS geom_json,
                     COALESCE(ex.items,'[]'::jsonb) AS exposures,
                     COALESCE(dep.items,'[]'::jsonb) AS dependencies,
                     COALESCE(candidate.items,'[]'::jsonb) AS dependency_candidates
              FROM energy_assets a
              LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                  'id',e.id,'hazardType',e.hazard_type,'hazardEventId',e.hazard_event_id,
                  'exposureStatus',e.exposure_status,'intersectionAreaM2',e.intersection_area_m2,
                  'intersectionLengthM',e.intersection_length_m,'distanceM',e.distance_m,
                  'evidenceKind',e.evidence_kind,'provenance',e.provenance,
                  'periodStart',e.assessment_period_start,'periodEnd',e.assessment_period_end
                ) ORDER BY e.hazard_type,e.id) AS items
                FROM asset_hazard_exposure e WHERE e.energy_asset_id=a.id
                  AND e.exposure_status IN ('exposed','not_exposed')
              ) ex ON TRUE
              LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object('serviceId',s.id,'serviceType',s.service_type,
                  'serviceName',s.name,'evidenceDatasetKey',d.evidence_dataset_key,
                  'evidence',d.evidence,'confidence',d.confidence,'verifiedAt',d.created_at)
                  ORDER BY s.service_type,s.id) AS items
                FROM service_dependencies d JOIN critical_services s ON s.id=d.critical_service_id
                WHERE d.energy_asset_id=a.id AND d.verified=TRUE
              ) dep ON TRUE
              LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object('serviceId',s.id,'serviceType',s.service_type,
                  'serviceName',s.name,'evidenceDatasetKey',d.evidence_dataset_key,
                  'evidence',d.evidence,'confidence',d.confidence,'verified',d.verified)
                  ORDER BY s.service_type,s.id) AS items
                FROM service_dependencies d JOIN critical_services s ON s.id=d.critical_service_id
                WHERE d.energy_asset_id=a.id AND d.verified=FALSE
              ) candidate ON TRUE
              WHERE a.id > %s::uuid
              ORDER BY a.id LIMIT %s
            """
        while True:
            with connection.cursor() as rows:
                rows.execute(asset_query, (last_asset_id, batch_size))
                batch = rows.fetchall()
            if not batch:
                break
            last_asset_id = batch[-1][0]
            with connection.cursor() as cur:
                critical_rows = []
                dependency_rows = []
                vulnerability_rows = []
                resilience_rows = []
                intervention_rows = []
                for asset_id, asset_type, name, voltage_kv, source_properties, geom_json, exposures, dependencies, candidates in batch:
                        counts["assets_processed"] += 1
                        props = source_properties if isinstance(source_properties, dict) else json.loads(source_properties or "{}")
                        exposures = exposures if isinstance(exposures, list) else json.loads(exposures or "[]")
                        dependencies = dependencies if isinstance(dependencies, list) else json.loads(dependencies or "[]")
                        candidates = candidates if isinstance(candidates, list) else json.loads(candidates or "[]")
                        asset_evidence = {"assetType": asset_type, "name": name, "voltageKv": voltage_kv,
                                          "sourceProperties": props, "verifiedServiceDependencies": dependencies,
                                          "dependencyCandidates": candidates}

                        # A verified relationship proves documented consequence context; it
                        # does not create a fabricated score or prove electrical connectivity.
                        criticality_status = "assessed" if dependencies else "unknown"
                        criticality_evidence = {**asset_evidence, "scoreStatus": "withheld",
                          "missingEvidence": ([] if dependencies else ["verified_service_dependency"])
                            + ["validated_network_topology", "served_load_or_population", "redundancy_evidence"],
                          "limitation": "No composite criticality score is calculated without a published, calibrated normalization and supported consequence data."}
                        critical_id = _stable_id("criticality", asset_id, criticality_evidence)
                        critical_rows.append((critical_id, asset_id, criticality_status, method, _canonical(criticality_evidence), run_id))

                        links = [("verified", item) for item in dependencies] + [("candidate", item) for item in candidates]
                        if not links:
                            links = [("unknown", None)]
                        for link_status, link in links:
                            dep_evidence = {"method": method, "relationship": link,
                              "coverageStatus": "recorded_relationship" if link else "no_relationship_dataset_for_asset",
                              "proximityUsedAsDependency": False}
                            service_id = link.get("serviceId") if link else None
                            dep_id = _stable_id("dependency", asset_id, dep_evidence)
                            dependency_rows.append((dep_id, asset_id, service_id, link_status, _canonical(dep_evidence),
                              link.get("confidence") if link else None, run_id))

                        missing_vulnerability = []
                        if not exposures:
                            missing_vulnerability.append("assessed_hazard_exposure")
                        if not dependencies:
                            missing_vulnerability.append("verified_service_dependency_or_served_population")
                        missing_vulnerability += ["asset_sensitivity_or_condition", "adaptive_capacity_or_redundancy"]
                        vuln_evidence = {"method": method, "observedHazardExposures": exposures,
                          "verifiedServiceDependencies": dependencies,
                          "scoreStatus": "withheld", "missingEvidence": missing_vulnerability,
                          "interpretation": "Screening score is unavailable; this is not a failure probability."}
                        vuln_id = _stable_id("vulnerability", asset_id, vuln_evidence)
                        vulnerability_rows.append((vuln_id, asset_id, _canonical({"observedHazardExposures": exposures}),
                           _canonical({"status": "not_assessed", "reason": "No verified redundancy/condition evidence"}),
                           _canonical(missing_vulnerability), method, _canonical(vuln_evidence), run_id))

                        resilience_criteria = {
                          "hazardExposure": {"status": "assessed" if exposures else "not_assessed", "records": len(exposures)},
                          "verifiedAlternativeSupply": {"status": "not_assessed", "reason": "No verified redundancy dataset"},
                          "networkConnectivity": {"status": "not_assessed", "reason": "No validated topology"},
                          "outageAndRestoration": {"status": "not_assessed", "reason": "No operational history"},
                          "serviceDependency": {"status": "assessed" if dependencies else "not_assessed", "records": len(dependencies)},
                        }
                        resilience_status = "partial" if exposures or dependencies else "unknown"
                        resilience_evidence = {"method": method, "criteria": resilience_criteria,
                          "compositeScore": "withheld", "interpretation": "Unknown dimensions are not treated as resilience."}
                        resilience_id = _stable_id("resilience", asset_id, resilience_evidence)
                        resilience_rows.append((resilience_id, asset_id, run_id, resilience_status,
                          _canonical(resilience_criteria), method, _canonical(resilience_evidence), geom_json))

                        exposed = [item for item in exposures if item.get("exposureStatus") == "exposed"]
                        if exposed:
                            scenario_evidence = {"method": method, "sourceExposureIds": [item["id"] for item in exposed],
                              "exposures": exposed, "ranking": "unranked_until_supported_criticality_exists"}
                            scenario_id = _stable_id("intervention", asset_id, scenario_evidence)
                            intervention_rows.append((scenario_id, asset_id, geom_json,
                               "Existing hazard exposure evidence warrants field verification and engineering review; no damage or mitigation effect is inferred.",
                               _canonical(scenario_evidence), _canonical({"mitigationEffect": "not_estimated", "costEffectiveness": "not_available"}), run_id))
                cur.executemany("""INSERT INTO asset_criticality_assessments
                  (id,energy_asset_id,status,score,method,evidence,confidence,processing_run_id,created_at)
                  VALUES (%s,%s,%s,NULL,%s,%s::jsonb,NULL,%s,NOW()) ON CONFLICT (id) DO NOTHING""", critical_rows)
                counts["criticality_assessments"] += max(cur.rowcount, 0)
                cur.executemany("""INSERT INTO service_dependency_assessments
                  (id,energy_asset_id,critical_service_id,status,evidence,confidence,processing_run_id,created_at)
                  VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,NOW()) ON CONFLICT (id) DO NOTHING""", dependency_rows)
                counts["dependency_assessments"] += max(cur.rowcount, 0)
                cur.executemany("""INSERT INTO asset_vulnerability_assessments
                  (id,energy_asset_id,status,vulnerability_class,score,sensitivity,adaptive_capacity,
                   missing_evidence,confidence,method,provenance,processing_run_id,created_at)
                  VALUES (%s,%s,'unknown',NULL,NULL,%s::jsonb,%s::jsonb,%s::jsonb,NULL,%s,%s::jsonb,%s,NOW())
                  ON CONFLICT (id) DO NOTHING""", vulnerability_rows)
                counts["vulnerability_assessments"] += max(cur.rowcount, 0)
                cur.executemany("""INSERT INTO grid_resilience_assessments
                  (id,energy_asset_id,processing_run_id,assessment_status,score,criteria,method,evidence,confidence,geom,created_at)
                  VALUES (%s,%s,%s,%s,NULL,%s::jsonb,%s,%s::jsonb,NULL,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),NOW())
                  ON CONFLICT (id) DO NOTHING""", resilience_rows)
                counts["resilience_assessments"] += max(cur.rowcount, 0)
                cur.executemany("""INSERT INTO intervention_scenarios
                  (id,energy_asset_id,area,action,priority,status,reason,evidence,assumptions,confidence,processing_run_id,created_at)
                  VALUES (%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),'field_verify_and_engineer_resilience_options',
                    'unranked','candidate',%s,%s::jsonb,%s::jsonb,NULL,%s,NOW()) ON CONFLICT (id) DO NOTHING""", intervention_rows)
                counts["intervention_candidates"] += max(cur.rowcount, 0)
            connection.commit()
            elapsed = time.monotonic() - assessment_started
            rate = (counts["assets_processed"] - resumed_assets) / max(elapsed, 0.001)
            eta = max(total_assets - counts["assets_processed"], 0) / max(rate, 0.001)
            with connection.cursor() as checkpoint:
                checkpoint.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                  (json.dumps({"assets_processed": counts["assets_processed"], "last_asset_id": last_asset_id,
                    "batch_size": batch_size}), run_id))
            connection.commit()
            print(f"Assessment progress: assets={counts['assets_processed']}/{total_assets}; criticality={counts['criticality_assessments']}; vulnerability={counts['vulnerability_assessments']}; resilience={counts['resilience_assessments']}; interventions={counts['intervention_candidates']}; elapsed={elapsed:.0f}s; eta={eta:.0f}s", flush=True)
            # Supabase's transaction pooler can drop long-lived client sessions.
            # Every batch is committed and checkpointed before refreshing, so
            # reconnecting never replays an uncommitted national-sized unit.
            if connection_dsn and time.monotonic() - session_started >= 45:
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_evidence_gated_assessments",))
                connection.commit()
                connection.close()
                import psycopg
                connection = psycopg.connect(connection_dsn, prepare_threshold=None, connect_timeout=15,
                    options="-c statement_timeout=120000", application_name="oseas-evidence-assessments")
                owns_connection = True
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_evidence_gated_assessments",))
                    acquired = cur.fetchone()[0]
                if not acquired:
                    connection.close()
                    raise RuntimeError("Another OSEAS evidence assessment run became active during connection refresh")
                session_started = time.monotonic()
                print("Assessment database session refreshed after committed checkpoint", flush=True)
        print("Assessment progress: aggregating current evidence by ward and county", flush=True)
        with connection.cursor() as cur:
            cur.execute("""SELECT u.id::text,u.unit_level,
                count(DISTINCT aa.energy_asset_id)::int AS assigned_assets,
                count(DISTINCT v.energy_asset_id)::int AS vulnerability_rows,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status IN ('exposed','not_exposed'))::int AS measured_exposure_assets,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status='exposed')::int AS exposed_assets,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status IN ('unknown','not_assessed'))::int AS unknown_exposure_assets,
                min(e.assessment_period_start),max(e.assessment_period_end)
              FROM administrative_units u
              LEFT JOIN asset_admin_assignments aa ON aa.administrative_unit_id=u.id AND aa.unit_level=u.unit_level AND aa.is_current=TRUE
              LEFT JOIN asset_vulnerability_assessments v ON v.energy_asset_id=aa.energy_asset_id AND v.processing_run_id=%s
              LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=aa.energy_asset_id
              WHERE u.unit_level IN ('ward','county') GROUP BY u.id,u.unit_level ORDER BY u.unit_level,u.id""", (run_id,))
            unit_rows = cur.fetchall()
            cur.execute("""SELECT u.id::text,e.hazard_type,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status IN ('exposed','not_exposed'))::int AS measured_assets,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status='exposed')::int AS exposed_assets,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status IN ('unknown','not_assessed'))::int AS unknown_assets
              FROM administrative_units u JOIN asset_admin_assignments aa
                ON aa.administrative_unit_id=u.id AND aa.unit_level=u.unit_level AND aa.is_current=TRUE
              JOIN asset_hazard_exposure e ON e.energy_asset_id=aa.energy_asset_id
              WHERE u.unit_level IN ('ward','county') GROUP BY u.id,e.hazard_type""")
            hazard_rows = cur.fetchall()
            hazards_by_unit: dict[str, dict[str, dict[str, int]]] = {}
            for unit_id, hazard_type, measured, exposed, unknown in hazard_rows:
                hazards_by_unit.setdefault(unit_id, {})[hazard_type] = {
                    "measuredAssets": measured, "exposedAssets": exposed, "unknownAssets": unknown}
            cur.execute("""SELECT aa.administrative_unit_id::text,lower(a.asset_type),count(DISTINCT a.id)::int
              FROM asset_admin_assignments aa JOIN energy_assets a ON a.id=aa.energy_asset_id
              WHERE aa.is_current=TRUE GROUP BY aa.administrative_unit_id,lower(a.asset_type)""")
            asset_type_counts: dict[str, dict[str, int]] = {}
            for unit_id, asset_type, asset_count in cur.fetchall():
                asset_type_counts.setdefault(unit_id, {})[asset_type] = asset_count
            summaries_by_level: dict[str, list[tuple[Any, ...]]] = {"ward": [], "county": []}
            for unit_id, level, assigned, vulnerability_rows, measured, exposed, unknown, period_start, period_end in unit_rows:
                hazard_counts = hazards_by_unit.get(unit_id, {})
                status = "not_assessed" if assigned == 0 else ("partial" if measured > 0 else "unknown")
                by_type = asset_type_counts.get(unit_id, {})
                system_classes = _system_class_counts(by_type)
                asset_counts = {"assignedAssets": assigned, "vulnerabilityAssessmentRows": vulnerability_rows,
                  "assetsWithMeasuredHazardExposure": measured, "assetsWithCandidateExposure": exposed,
                  "assetsWithUnknownExposure": unknown, "assetTypeCounts": by_type,
                  "systemClassCounts": system_classes, "compositeVulnerabilityScoreAvailable": 0}
                provenance = {"method": method, "assessmentRunId": str(run_id),
                  "scoreStatus": "withheld", "summaryUnit": level,
                  "systemClassMethod": "inventory asset_type grouping only; does not infer feeders, islanding, or electrical connectivity",
                  "missingEvidence": ["validated asset condition and sensitivity", "adaptive capacity and redundancy",
                    "verified service dependencies or served population", "calibrated vulnerability normalization"],
                  "interpretation": "Administrative screening summary of stored asset evidence; it is not an outage probability or validated vulnerability score."}
                summary_id = _stable_id(f"{level}_vulnerability_summary", unit_id, "current")
                summaries_by_level[level].append((summary_id, unit_id, run_id, period_start, period_end,
                  status, _canonical(asset_counts), _canonical(hazard_counts), _canonical(provenance)))
            print(f"Assessment aggregation: prepared ward={len(summaries_by_level['ward'])}; county={len(summaries_by_level['county'])}; persisting in batches", flush=True)
            for level, target in (("ward", "ward_vulnerability_summary"), ("county", "county_vulnerability_summary")):
                summary_rows = summaries_by_level[level]
                if summary_rows:
                    cur.executemany(f"""INSERT INTO {target}
                      (id,{level}_id,assessment_run_id,period_start,period_end,summary_status,asset_counts,hazard_counts,confidence,provenance,created_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,NULL,%s::jsonb,NOW())
                      ON CONFLICT(id) DO UPDATE SET assessment_run_id=EXCLUDED.assessment_run_id,
                        period_start=EXCLUDED.period_start,period_end=EXCLUDED.period_end,summary_status=EXCLUDED.summary_status,
                        asset_counts=EXCLUDED.asset_counts,hazard_counts=EXCLUDED.hazard_counts,
                        provenance=EXCLUDED.provenance,created_at=NOW()""", summary_rows)
                    counts[f"{level}_vulnerability_summaries"] += len(summary_rows)
        connection.commit()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
                        (_canonical(counts), run_id))
        connection.commit()
    except Exception as error:
        status = "partial" if counts["assets_processed"] else "failed"
        try:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute("UPDATE ingestion_runs SET status=%s,finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s",
                            (status, str(error)[:4000], _canonical(counts), run_id))
            connection.commit()
        except Exception:
            # Supavisor can drop a long-lived client connection. Keep all prior
            # committed batches and mark the run resumable using a fresh session.
            try:
                import psycopg
                recovery_dsn = connection_dsn or connection.info.dsn
                with psycopg.connect(recovery_dsn, prepare_threshold=None, connect_timeout=15,
                                     options="-c statement_timeout=30000",
                                     application_name="oseas-evidence-assessments-recovery") as recovery:
                    with recovery.cursor() as cur:
                        cur.execute("UPDATE ingestion_runs SET status=%s,finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s AND status='running'",
                                    (status, str(error)[:4000], _canonical(counts), run_id))
                    recovery.commit()
            except Exception:
                pass
        raise
    finally:
        try:
            if not connection.closed:
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_evidence_gated_assessments",))
                connection.commit()
        except Exception:
            pass
        if owns_connection:
            try:
                connection.close()
            except Exception:
                pass
    return {**counts, "run_id": str(run_id), "status": "completed"}
