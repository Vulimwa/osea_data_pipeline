"""Coverage-aware zonal population estimates for observed flood footprints.

WorldPop values are estimated persons per pixel. This module reports people
residing in valid raster cells whose centers fall inside each footprint. It
does not estimate people served by or dependent on any energy asset.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import rasterio
_RASTERIO_PROJ = str(Path(rasterio.__file__).resolve().parent / "proj_data")
if (Path(_RASTERIO_PROJ) / "proj.db").exists():
    os.environ["PROJ_LIB"] = _RASTERIO_PROJ
    os.environ["PROJ_DATA"] = _RASTERIO_PROJ
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import GeometryCollection, mapping
from shapely.ops import unary_union
from shapely import wkb
from shapely import clip_by_rect

DATASET_KEY = "worldpop_global2_kenya_population_100m"
WORLDPOP_ATTRIBUTION = "WorldPop Global2 R2025A v1; CC BY 4.0"
METHOD = "worldpop_cell_center_zonal_sum_v1"
ID_NAMESPACE = uuid.UUID("c1980d5a-2f73-4ae7-9c4d-050a4f49e9ad")


@dataclass
class Zone:
    key: str
    name: str | None
    level: str | None
    geometries: list[Any]
    kind: str


def _pixel_stats(src: rasterio.io.DatasetReader, geometries: list[Any], tile_size: int = 512) -> dict[str, Any]:
    """Sum valid population cells within a polygon using bounded raster reads."""
    if hasattr(geometries, "geom_type"):
        geometries = [geometries]
    geometries = [geom for geom in geometries if geom is not None and not geom.is_empty]
    if not geometries:
        return {"population": None, "inside_pixels": 0, "valid_pixels": 0, "valid_fraction": None}
    bounds = (min(geom.bounds[0] for geom in geometries), min(geom.bounds[1] for geom in geometries),
              max(geom.bounds[2] for geom in geometries), max(geom.bounds[3] for geom in geometries))
    raster_bounds = src.bounds
    if (bounds[2] <= raster_bounds.left or bounds[0] >= raster_bounds.right
            or bounds[3] <= raster_bounds.bottom or bounds[1] >= raster_bounds.top):
        return {"population": None, "inside_pixels": 0, "valid_pixels": 0, "valid_fraction": None}
    window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
    if window.width <= 0 or window.height <= 0:
        return {"population": None, "inside_pixels": 0, "valid_pixels": 0, "valid_fraction": None}
    window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
    if window.width <= 0 or window.height <= 0:
        return {"population": None, "inside_pixels": 0, "valid_pixels": 0, "valid_fraction": None}

    inside_count = valid_count = 0
    population = 0.0
    started = time.monotonic()
    total_tiles = ((int(window.height) + tile_size - 1) // tile_size) * ((int(window.width) + tile_size - 1) // tile_size)
    processed_tiles = 0
    for row in range(int(window.row_off), int(window.row_off + window.height), tile_size):
        height = min(tile_size, int(window.row_off + window.height) - row)
        for col in range(int(window.col_off), int(window.col_off + window.width), tile_size):
            width = min(tile_size, int(window.col_off + window.width) - col)
            tile = rasterio.windows.Window(col, row, width, height)
            processed_tiles += 1
            transform = src.window_transform(tile)
            left, bottom, right, top = rasterio.windows.bounds(tile, src.transform)
            tile_geometries = [clip_by_rect(geom, left, bottom, right, top) for geom in geometries]
            tile_geometries = [geom for geom in tile_geometries if not geom.is_empty]
            if not tile_geometries:
                continue
            # Rasterizing several polygons into one boolean mask counts any shared
            # pixel once, without an expensive topology dissolve.
            mask = geometry_mask([mapping(geom) for geom in tile_geometries], out_shape=(height, width), transform=transform,
                                  invert=True, all_touched=False)
            cells_in = int(mask.sum())
            if not cells_in:
                continue
            values = src.read(1, window=tile, masked=True)
            valid = mask & ~np.ma.getmaskarray(values)
            raw = np.asarray(values.data, dtype="float64")
            valid &= np.isfinite(raw) & (raw >= 0)
            inside_count += cells_in
            valid_count += int(valid.sum())
            if valid.any():
                population += float(raw[valid].sum(dtype="float64"))
            if processed_tiles == 1 or processed_tiles % 10 == 0 or processed_tiles == total_tiles:
                elapsed = time.monotonic() - started
                rate = processed_tiles / elapsed if elapsed else 0
                eta = (total_tiles - processed_tiles) / rate if rate else None
                eta_text = f"{eta:.0f}s" if eta is not None else "unknown"
                print(f"WorldPop raster progress: tiles={processed_tiles}/{total_tiles}; valid_pixels={valid_count}; elapsed={elapsed:.0f}s; eta={eta_text}", flush=True)
    return {
        "population": population if valid_count else None,
        "inside_pixels": inside_count,
        "valid_pixels": valid_count,
        "valid_fraction": valid_count / inside_count if inside_count else None,
    }


def summarize_footprints(raster_path: Path, events: Iterable[dict[str, Any]], *, year: int = 2024,
                         tile_size: int = 512) -> dict[str, Any]:
    """Summarize event unions and optional administrative zones from real raster cells."""
    results: list[dict[str, Any]] = []
    with rasterio.open(raster_path) as src:
        if src.count != 1 or not src.crs or src.crs.to_epsg() != 4326:
            raise ValueError("WorldPop input must be a single-band EPSG:4326 population-count raster")
        for event in events:
            geometries = [item["geom"] for item in event["features"] if item["geom"] is not None and not item["geom"].is_empty]
            if not geometries:
                continue
            fingerprint = hashlib.sha256()
            for item in sorted(event["features"], key=lambda feature: feature.get("source_feature_id", "")):
                fingerprint.update(str(item.get("source_feature_id", "")).encode("utf-8"))
                fingerprint.update(wkb.dumps(item["geom"], output_dimension=2))
            event["source_geometry_sha256"] = fingerprint.hexdigest()
            print(f"WorldPop {event['event_key']}: combining {len(geometries)} source footprint(s) in a single raster mask", flush=True)
            event_geom = GeometryCollection(geometries)
            zones = [Zone(event["event_key"], event.get("event_key"), None, geometries, "event")]
            for admin in event.get("administrative_units", []):
                clipped_geometries = [geom.intersection(admin["geom"]) for geom in geometries if geom.intersects(admin["geom"])]
                clipped_geometries = [geom for geom in clipped_geometries if not geom.is_empty and geom.area > 0]
                if clipped_geometries:
                    zones.append(Zone(str(admin["id"]), admin.get("name"), admin["unit_level"], clipped_geometries, "administrative_unit"))
            summaries = []
            for index, zone in enumerate(zones, 1):
                stats = _pixel_stats(src, zone.geometries, tile_size=tile_size)
                summaries.append({
                    "zone_key": zone.key,
                    "zone_name": zone.name,
                    "reporting_unit_level": zone.level,
                    "kind": zone.kind,
                    "geometry": GeometryCollection(zone.geometries),
                    **stats,
                })
                print(f"WorldPop {event['event_key']}: zonal summary {index}/{len(zones)} ({zone.kind} {zone.name or zone.key}); valid_pixels={stats['valid_pixels']}", flush=True)
            results.append({
                "event_key": event["event_key"],
                "source_geometry_sha256": event["source_geometry_sha256"],
                "event_dates": sorted({item.get("event_date") for item in event["features"] if item.get("event_date")}),
                "source_feature_count": len(geometries),
                "geometry": event_geom,
                "zones": summaries,
            })
    return {
        "dataset_key": DATASET_KEY,
        "provider": "WorldPop Global2 R2025A v1",
        "population_reference_year": year,
        "population_units": "estimated persons",
        "source_resolution_arc_seconds": 3,
        "method": METHOD,
        "pixel_inclusion": "pixel center within footprint; overlapping event polygons unioned before counting",
        "attribution": WORLDPOP_ATTRIBUTION,
        "scientific_validation_status": "not_validated_for_event_population_counts",
        "limitations": [
            "WorldPop is a modeled gridded population estimate, not a census count at each cell.",
            "Counts describe estimated residents within the reference footprint, not confirmed people impacted or served by an energy asset.",
            "Cells are counted once within each event union; separate events may overlap in time and are not additive.",
            "Only valid raster cells are summed; valid_fraction reports raster-cell coverage of the footprint.",
            "WorldPop Global2 R2025A is an alpha release and may be revised.",
        ],
        "events": results,
    }


def stable_assessment_id(*parts: str) -> str:
    """Stable UUID across reruns of the same source version, event and zone."""
    return str(uuid.uuid5(ID_NAMESPACE, "|".join(parts)))


def raster_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_events(connection: Any, source_dataset_key: str) -> list[dict[str, Any]]:
    from shapely import wkb

    with connection.cursor() as cur:
        cur.execute("""SELECT event_key,event_date,ST_AsBinary(geom) AS geom,source_feature_id,event_metadata
                      FROM flood_reference_features WHERE dataset_key=%s ORDER BY event_key,source_feature_id""", (source_dataset_key,))
        records = cur.fetchall()
    groups: dict[str, dict[str, Any]] = {}
    for key, event_date, geom_bytes, feature_id, metadata in records:
        group = groups.setdefault(key, {"event_key": key, "features": []})
        group["features"].append({"geom": wkb.loads(bytes(geom_bytes)), "event_date": event_date.isoformat() if event_date else None,
                                  "source_feature_id": feature_id, "event_metadata": metadata})
    return list(groups.values())


def _db_admin_units(connection: Any, event_geom: Any) -> list[dict[str, Any]]:
    from shapely import wkb

    # Do exact intersection in PostGIS so its GiST index prunes the county/ward table.
    event_wkb = wkb.dumps(event_geom, output_dimension=2)
    with connection.cursor() as cur:
        cur.execute("""SELECT id::text,unit_level,name,ST_AsBinary(geom) AS geom
                      FROM administrative_units
                      WHERE unit_level IN ('county','ward')
                        AND ST_Intersects(geom,ST_GeomFromWKB(%s,4326))""", (event_wkb,))
        records = cur.fetchall()
    return [{"id": row[0], "unit_level": row[1], "name": row[2], "geom": wkb.loads(bytes(row[3]))} for row in records]


def persist_summaries(connection: Any, summary: dict[str, Any], raster_path: Path, source_dataset_key: str,
                      source_version: str) -> dict[str, int]:
    """Persist repeatable population estimates with per-output provenance and coverage."""
    run_id = uuid.uuid4()
    raster_hash = raster_sha256(raster_path)
    dataset_source = f"https://hub.worldpop.org/geodata/listing?id=135; {source_version}; SHA256={raster_hash}"
    row_count = 0
    unit_count = 0
    coverage_count = 0
    processed_zones = 0
    # The installed unique index allows one coverage row per reporting unit
    # and run. Aggregate event footprints by unit while keeping the population
    # estimate rows event-specific.
    coverage_by_unit: dict[str, dict[str, Any]] = {}
    for event in summary["events"]:
        for zone in event["zones"]:
            if zone["kind"] != "administrative_unit":
                continue
            aggregate = coverage_by_unit.setdefault(zone["zone_key"], {
                "reporting_unit_level": zone["reporting_unit_level"], "geometries": [],
                "inside_pixels": 0, "valid_pixels": 0, "event_keys": [], "event_dates": [],
            })
            aggregate["geometries"].append(zone["geometry"])
            aggregate["inside_pixels"] += zone["inside_pixels"]
            aggregate["valid_pixels"] += zone["valid_pixels"]
            aggregate["event_keys"].append(event["event_key"])
            aggregate["event_dates"].extend(event["event_dates"])
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_worldpop_population_exposure",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another WorldPop exposure persistence run is active")
        cur.execute("""INSERT INTO datasets (dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
                       VALUES (%s,%s,'worldpop_raster',%s,'population','CC BY 4.0',%s,TRUE)
                       ON CONFLICT (dataset_key) DO UPDATE SET name=EXCLUDED.name,source_reference=EXCLUDED.source_reference,
                         category=EXCLUDED.category,licence=EXCLUDED.licence,attribution=EXCLUDED.attribution,updated_at=NOW()""",
                    (DATASET_KEY, "WorldPop Global2 Kenya population counts 100m", dataset_source, WORLDPOP_ATTRIBUTION))
        cur.execute("INSERT INTO ingestion_runs (id,pipeline_name,status,metadata) VALUES (%s,'oseas_worldpop_population_exposure','running',%s::jsonb)",
                    (run_id, json.dumps({"dataset_key": DATASET_KEY, "flood_reference_dataset_key": source_dataset_key,
                                         "population_reference_year": summary["population_reference_year"], "method": METHOD,
                                         "raster_sha256": raster_hash})))
        connection.commit()
    try:
        with connection.cursor() as cur:
            population_sql = """INSERT INTO population_exposure_assessments
              (id,dataset_key,hazard_event_id,processing_run_id,reporting_unit_id,population_total,
               population_potentially_exposed,assessment_status,method,evidence,confidence,geom,created_at)
              VALUES (%s,%s,NULL,%s,%s,NULL,%s,%s,%s,%s::jsonb,NULL,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),NOW())
              ON CONFLICT (id) DO UPDATE SET processing_run_id=EXCLUDED.processing_run_id,
                population_potentially_exposed=EXCLUDED.population_potentially_exposed,
                assessment_status=EXCLUDED.assessment_status,evidence=EXCLUDED.evidence,geom=EXCLUDED.geom,created_at=NOW()"""
            coverage_sql = """INSERT INTO spatial_coverage_assessments
              (id,dataset_key,processing_run_id,reporting_unit_id,reporting_unit_level,hazard_type,evidence_kind,
               observation_start,observation_end,coverage_status,valid_data_fraction,observation_footprint,
               valid_data_footprint,quality_mask,validation_status,limitations,provenance)
              VALUES (%s,%s,%s,%s,%s,'flood','observed',%s::date,%s::date,%s,%s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),
                %s::jsonb,'not_validated',%s::jsonb,%s::jsonb)
              ON CONFLICT(id) DO UPDATE SET processing_run_id=EXCLUDED.processing_run_id,
                valid_data_fraction=EXCLUDED.valid_data_fraction,observation_footprint=EXCLUDED.observation_footprint,
                valid_data_footprint=EXCLUDED.valid_data_footprint,quality_mask=EXCLUDED.quality_mask,
                limitations=EXCLUDED.limitations,provenance=EXCLUDED.provenance,created_at=NOW()"""
            population_batch = []
            coverage_batch = []
            total_zones = sum(len(event["zones"]) for event in summary["events"])

            def flush_batch() -> None:
                nonlocal row_count, coverage_count
                if population_batch:
                    cur.executemany(population_sql, population_batch)
                    row_count += max(cur.rowcount, 0)
                if coverage_batch:
                    cur.executemany(coverage_sql, coverage_batch)
                    coverage_count += max(cur.rowcount, 0)
                cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                            (json.dumps({"persisted_population_rows": row_count, "persisted_coverage_rows": coverage_count,
                                         "processed_zones": processed_zones}), run_id))
                connection.commit()
                population_batch.clear()
                coverage_batch.clear()
                print(f"WorldPop persistence progress: zones={processed_zones}/{total_zones}; population_rows={row_count}; coverage_rows={coverage_count}", flush=True)

            for event in summary["events"]:
                event_dates = event["event_dates"]
                period_start = min(event_dates) if event_dates else None
                period_end = max(event_dates) if event_dates else None
                for zone in event["zones"]:
                    # Identity incorporates the source version, population raster and event/admin scope.
                    stable_id = stable_assessment_id(raster_hash, event["event_key"], event["source_geometry_sha256"], zone["kind"], zone["zone_key"])
                    geom_json = json.dumps(mapping(zone["geometry"]))
                    evidence = {
                        "provider": summary["provider"], "populationReferenceYear": summary["population_reference_year"],
                        "units": summary["population_units"], "resolutionArcSeconds": summary["source_resolution_arc_seconds"],
                        "method": summary["method"], "pixelInclusion": summary["pixel_inclusion"],
                        "validRasterPixels": zone["valid_pixels"], "footprintRasterPixels": zone["inside_pixels"],
                        "validRasterFraction": zone["valid_fraction"], "sourceRasterSha256": raster_hash,
                        "floodReferenceDatasetKey": source_dataset_key, "eventKey": event["event_key"],
                        "eventDates": event_dates, "floodReferenceGeometrySha256": event["source_geometry_sha256"],
                        "limitations": summary["limitations"],
                        "scientificValidationStatus": summary["scientific_validation_status"],
                    }
                    status = ("unknown" if not zone["valid_pixels"] else
                              ("assessed" if zone["valid_fraction"] == 1 else "partial"))
                    population_batch.append((stable_id, DATASET_KEY, run_id,
                      zone["zone_key"] if zone["kind"] == "administrative_unit" else None,
                      zone["population"], status, METHOD, json.dumps(evidence), geom_json))
                    unit_count += int(zone["kind"] == "administrative_unit")
                    if zone["kind"] == "event":
                        # Event-specific coverage is already attached to the
                        # population row. The installed run-scope unique index
                        # cannot distinguish multiple event-level NULL scopes.
                        pass
                    processed_zones += 1
                    if processed_zones % 25 == 0 or processed_zones == total_zones:
                        flush_batch()
            for zone_key, aggregate in coverage_by_unit.items():
                inside_pixels = aggregate["inside_pixels"]
                valid_pixels = aggregate["valid_pixels"]
                valid_fraction = valid_pixels / inside_pixels if inside_pixels else None
                coverage_geom = unary_union(aggregate["geometries"])
                coverage_geom_json = json.dumps(mapping(coverage_geom))
                coverage_id = stable_assessment_id(raster_hash, "admin_coverage", zone_key)
                event_keys = sorted(set(aggregate["event_keys"]))
                event_dates = sorted(set(aggregate["event_dates"]))
                coverage_batch.append((coverage_id, DATASET_KEY, run_id, zone_key,
                  aggregate["reporting_unit_level"] or "national", min(event_dates) if event_dates else None,
                  max(event_dates) if event_dates else None,
                  "partially_assessed" if valid_fraction not in (1, None) else ("assessed" if valid_pixels else "insufficient_data"),
                  valid_fraction, coverage_geom_json, coverage_geom_json if valid_fraction == 1 else None,
                  json.dumps({"insidePixels": inside_pixels, "validPixels": valid_pixels}),
                  json.dumps(summary["limitations"]), json.dumps({"method": METHOD, "sourceRasterSha256": raster_hash,
                    "eventKeys": event_keys, "processingRunId": str(run_id)})))
                if len(coverage_batch) >= 25:
                    flush_batch()
            if coverage_batch:
                flush_batch()
            cur.execute("""INSERT INTO dataset_versions (dataset_key,source_reference,source_version,checksum,retrieved_at,
                       observation_start,observation_end,feature_count,metadata,processing_run_id)
                       SELECT %s,%s,%s,%s,NOW(),NULL,NULL,%s,%s::jsonb,%s
                       WHERE NOT EXISTS (SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
                        (DATASET_KEY, dataset_source, source_version, raster_hash, row_count,
                         json.dumps({"year": summary["population_reference_year"], "units": "persons/pixel", "method": METHOD}), run_id,
                         DATASET_KEY, raster_hash))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("INSERT INTO data_quality_checks (run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'worldpop_raster_and_coverage','warning',%s::jsonb)",
                        (run_id, DATASET_KEY, json.dumps({"rasterSha256": raster_hash, "populationReferenceYear": summary["population_reference_year"],
                                                          "assessmentRows": row_count, "administrativeRows": unit_count, "coverageRows": coverage_count,
                                                          "scientificValidationStatus": summary["scientific_validation_status"],
                                                          "limitations": summary["limitations"]})))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
                        (json.dumps({"assessment_rows": row_count, "administrative_rows": unit_count,
                          "coverage_rows": coverage_count, "raster_sha256": raster_hash}), run_id))
        connection.commit()
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status=%s,finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s",
                        ("partial" if row_count else "failed", str(error)[:4000],
                         json.dumps({"persisted_population_rows": row_count, "persisted_coverage_rows": coverage_count,
                                     "processed_zones": processed_zones}), run_id))
        connection.commit()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_worldpop_population_exposure",))
        connection.commit()
    return {"assessment_rows": row_count, "administrative_rows": unit_count,
            "coverage_rows": coverage_count, "run_id": str(run_id)}


def events_from_local_unosat(source_dir: Path) -> list[dict[str, Any]]:
    """Read local reference polygons without touching Supabase (audit/dry-run mode)."""
    from .local_flood_reference import read_reference_features
    from shapely import wkb

    groups: dict[str, dict[str, Any]] = {}
    for record in read_reference_features(source_dir, progress=True):
        group = groups.setdefault(record["event_key"], {"event_key": record["event_key"], "features": []})
        group["features"].append({"geom": wkb.loads(record["geometry_wkb"]), "event_date": record["event_date"],
                                  "source_feature_id": record["source_feature_id"], "event_metadata": record["event_metadata"]})
    return list(groups.values())


def attach_admin_units(connection: Any, events: list[dict[str, Any]]) -> None:
    for event in events:
        geoms = [item["geom"] for item in event["features"]]
        event_geom = GeometryCollection(geoms)
        print(f"WorldPop {event['event_key']}: querying indexed county/ward intersections", flush=True)
        event["administrative_units"] = _db_admin_units(connection, event_geom)
        print(f"WorldPop {event['event_key']}: found {len(event['administrative_units'])} intersecting county/ward units", flush=True)


def persist_local_results(path: Path, summary: dict[str, Any], raster_path: Path) -> None:
    """Write a compact map preview and manifest for non-DB runs.

    Population sums use the original exact geometry. The preview geometry is
    simplified for display only to avoid duplicating hundreds of MB of source
    vertices already present in the reference flood layer.
    """
    display_tolerance_degrees = 0.0005
    features = []
    for event in summary["events"]:
        for zone in event["zones"]:
            geom = zone.pop("geometry")
            display_geom = geom.simplify(display_tolerance_degrees, preserve_topology=True)
            features.append({"type": "Feature", "geometry": mapping(display_geom), "properties": {
                "eventKey": event["event_key"], "zoneKey": zone["zone_key"], "zoneName": zone["zone_name"],
                "reportingUnitLevel": zone["reporting_unit_level"], "assessmentType": zone["kind"],
                "populationPotentiallyExposed": zone["population"], "populationReferenceYear": summary["population_reference_year"],
                "validRasterPixels": zone["valid_pixels"], "footprintRasterPixels": zone["inside_pixels"],
                "validRasterFraction": zone["valid_fraction"], "method": summary["method"],
                "displayGeometrySimplificationDegrees": display_tolerance_degrees,
            }})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)
    manifest = {key: value for key, value in summary.items() if key != "events"}
    manifest["raster_sha256"] = raster_sha256(raster_path)
    manifest["events"] = [{"event_key": event["event_key"], "event_dates": event["event_dates"],
                           "source_feature_count": event["source_feature_count"], "zones": [
                               {key: value for key, value in zone.items() if key != "geometry"}
                               for zone in event["zones"]]} for event in summary["events"]]
    path.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

