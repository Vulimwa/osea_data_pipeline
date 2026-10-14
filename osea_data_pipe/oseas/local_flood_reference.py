"""Read and validate the supplied UNOSAT 2024 flood reference shapefiles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

import fiona
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shapely import wkb

DATASET_KEY = "kenya_flood_2024_unosat"
EVENT_KEY_FALLBACK = "FL20240426KEN"
DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[1] / "KENYA_FLOOD_2024_SHP_UNOSAT"


def selected_files(source_dir: Path) -> list[Path]:
    """Select event flood polygons, excluding water context and impact layers."""
    files = sorted(source_dir.glob("*FloodExtent*.shp"))
    files += sorted(source_dir.glob("*MaximumFloodWaterExtent*.shp"))
    files = sorted(set(files))
    if not files:
        raise FileNotFoundError(f"No UNOSAT flood extent shapefiles found in {source_dir}")
    return files


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _bundle_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    for sidecar in sorted(path.parent.glob(f"{path.stem}.*")):
        if sidecar.suffix.casefold() not in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
            continue
        digest.update(sidecar.suffix.casefold().encode("ascii"))
        with sidecar.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _event_date(properties: dict[str, Any], filename: str) -> str | None:
    for key, value in properties.items():
        if key.casefold() in {"sensor_dat", "event_date", "date_proc"} and value:
            text = _json_value(value)
            try:
                return date.fromisoformat(str(text)[:10]).isoformat()
            except ValueError:
                digits = re.sub(r"\D", "", str(text))[:8]
                if len(digits) == 8:
                    try:
                        return datetime.strptime(digits, "%Y%m%d").date().isoformat()
                    except ValueError:
                        pass
    match = re.search(r"(?:PL|S2)_(\d{8})_", filename)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    return None


def read_reference_features(source_dir: Path = DEFAULT_SOURCE_DIR, *, progress: bool = False) -> Iterator[dict[str, Any]]:
    """Stream polygon records, reproject to WGS84, and retain source properties."""
    for path in selected_files(source_dir):
        if progress:
            print(f"UNOSAT: reading and normalizing {path.name}", flush=True)
        checksum = _bundle_checksum(path)
        with fiona.open(path) as source:
            if not source.crs and not source.crs_wkt:
                raise ValueError(f"Missing coordinate reference system: {path.name}")
            source_crs = CRS.from_user_input(source.crs_wkt or source.crs)
            transformer = None if source_crs.to_epsg() == 4326 else Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True).transform
            for ordinal, feature in enumerate(source):
                if not feature.get("geometry"):
                    raise ValueError(f"Feature {ordinal} in {path.name} has no geometry")
                geom = shape(feature["geometry"])
                if transformer:
                    geom = transform(transformer, geom)
                if geom.geom_type not in {"Polygon", "MultiPolygon"} or geom.is_empty:
                    raise ValueError(f"Expected a non-empty polygon in {path.name}; found {geom.geom_type}")
                properties = {str(key): _json_value(value) for key, value in dict(feature["properties"]).items()}
                event_key = next((str(value).strip() for key, value in properties.items()
                                  if key.casefold() in {"eventcode", "event_id", "eventid"} and value), EVENT_KEY_FALLBACK)
                source_id = f"{path.stem}:{feature.get('id', ordinal)}"
                geometry_wkb = wkb.dumps(geom, output_dimension=2)
                if progress:
                    print(f"UNOSAT: normalized {path.name} feature {ordinal + 1}", flush=True)
                yield {
                    "source_feature_id": source_id,
                    "event_key": event_key,
                    "event_date": _event_date(properties, path.name),
                    "source_properties": properties,
                    "event_metadata": {
                        "provider": "UNOSAT",
                        "source_file": path.name,
                        "source_file_sha256": checksum,
                        "source_crs": source_crs.to_string(),
                        "event_code": event_key,
                        "evidence_kind": "reference_observation",
                        "confidence_status": next((str(value) for key, value in properties.items()
                                                    if key.casefold() == "confidence" and value), None),
                        "field_validation_status": next((str(value) for key, value in properties.items()
                                                        if key.casefold() in {"field_vali", "field_validation"} and value), None),
                        "source_reported_area_m2": next((value for key, value in properties.items()
                                                        if key.casefold() in {"area_m2", "shape_area"} and isinstance(value, (int, float))), None),
                    },
                    "geometry_type": geom.geom_type,
                    # WKB avoids expanding these large polygons into much larger GeoJSON strings.
                    "geometry_wkb": geometry_wkb,
                }


def inspect_reference(source_dir: Path = DEFAULT_SOURCE_DIR) -> dict[str, Any]:
    """Perform a local, read-only audit suitable before database setup."""
    files = selected_files(source_dir)
    feature_count = 0
    event_keys: set[str] = set()
    event_dates: set[str] = set()
    geometry_types: set[str] = set()
    validation_statuses: set[str] = set()
    for path in files:
        with fiona.open(path) as source:
            if not source.crs and not source.crs_wkt:
                raise ValueError(f"Missing coordinate reference system: {path.name}")
            feature_count += len(source)
            geometry_types.add(str(source.schema.get("geometry", "unknown")))
            for feature in source:
                properties = {str(key): _json_value(value) for key, value in dict(feature["properties"]).items()}
                event_key = next((str(value).strip() for key, value in properties.items()
                                  if key.casefold() in {"eventcode", "event_id", "eventid"} and value), EVENT_KEY_FALLBACK)
                event_keys.add(event_key)
                if found_date := _event_date(properties, path.name):
                    event_dates.add(found_date)
                validation_status = next((str(value) for key, value in properties.items()
                                          if key.casefold() in {"field_vali", "field_validation"} and value), None)
                if validation_status:
                    validation_statuses.add(validation_status)
    return {
        "dataset_key": DATASET_KEY,
        "source_directory": str(source_dir),
        "files": [path.name for path in files],
        "feature_count": feature_count,
        "event_keys": sorted(event_keys),
        "event_dates": sorted(event_dates),
        "geometry_types": sorted(geometry_types),
        "geometry_normalization": "PostGIS ST_MakeValid will normalize source polygons during ingest",
        "field_validation_statuses": sorted(validation_statuses),
    }


def _ensure_dataset(cur: Any, source_dir: Path) -> None:
    cur.execute(
        """INSERT INTO datasets (dataset_key, name, source_type, source_reference, category, is_optional, attribution)
           VALUES (%s, %s, 'local_shapefile', %s, 'flood_reference', TRUE, %s)
           ON CONFLICT (dataset_key) DO UPDATE SET name=EXCLUDED.name,
             source_reference=EXCLUDED.source_reference, category=EXCLUDED.category,
             attribution=EXCLUDED.attribution, updated_at=NOW()""",
        (DATASET_KEY, "UNOSAT Kenya 2024 flood reference extents", str(source_dir.resolve()), "UNOSAT; retain source attribution and product-specific terms"),
    )


def ingest_reference(connection: Any, source_dir: Path = DEFAULT_SOURCE_DIR, batch_size: int = 100) -> dict[str, Any]:
    """Idempotently batch-upsert local event polygons and their run provenance."""
    summary = inspect_reference(source_dir)
    print(f"UNOSAT: {summary['feature_count']} reference polygons across {len(summary['files'])} shapefiles; events={','.join(summary['event_keys'])}", flush=True)
    records = list(read_reference_features(source_dir, progress=True))
    run_id = __import__("uuid").uuid4()
    inserted = 0
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_local_flood_reference_ingest",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another OSEAS local flood reference ingestion is active")
        _ensure_dataset(cur, source_dir)
        cur.execute(
            "INSERT INTO ingestion_runs (id,pipeline_name,status,metadata) VALUES (%s,'oseas_local_flood_reference_ingest','running',%s::jsonb)",
            (run_id, json.dumps({"dataset_key": DATASET_KEY, "source_feature_count": len(records)})),
        )
    connection.commit()
    try:
        for offset in range(0, len(records), batch_size):
            batch = records[offset:offset + batch_size]
            with connection.cursor() as cur:
                cur.executemany(
                    """INSERT INTO flood_reference_features
                         (dataset_key,source_feature_id,event_key,event_date,source_properties,event_metadata,geom,processing_run_id,updated_at)
                       VALUES (%s,%s,%s,%s::date,%s::jsonb,%s::jsonb,
                         ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_GeomFromWKB(%s,4326)),3)),%s,NOW())
                       ON CONFLICT (dataset_key,source_feature_id) DO UPDATE SET event_key=EXCLUDED.event_key,
                         event_date=EXCLUDED.event_date,source_properties=EXCLUDED.source_properties,
                         event_metadata=EXCLUDED.event_metadata,geom=EXCLUDED.geom,
                         processing_run_id=EXCLUDED.processing_run_id,updated_at=NOW()""",
                    [(DATASET_KEY, row["source_feature_id"], row["event_key"], row["event_date"],
                      json.dumps(row["source_properties"]), json.dumps(row["event_metadata"]),
                      row["geometry_wkb"], run_id) for row in batch],
                )
                cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
                cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s", (json.dumps({"processed": offset + len(batch)}), run_id))
            connection.commit()
            inserted += len(batch)
            print(f"UNOSAT flood reference progress: {inserted}/{len(records)} polygons upserted", flush=True)
        with connection.cursor() as cur:
            hashes = sorted({row["event_metadata"]["source_file_sha256"] for row in records})
            cur.execute("INSERT INTO dataset_versions (dataset_key,source_reference,retrieved_at,feature_count,metadata,processing_run_id) VALUES (%s,%s,NOW(),%s,%s::jsonb,%s)",
                        (DATASET_KEY, str(source_dir.resolve()), inserted, json.dumps({"files": [p.name for p in selected_files(source_dir)], "sha256": hashes, "event_keys": sorted({row['event_key'] for row in records})}), run_id))
            cur.execute("INSERT INTO data_quality_checks (run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'local_reference_geometry_validation','warning',%s::jsonb)",
                        (run_id, DATASET_KEY, json.dumps({"feature_count": inserted, "validation_status": "source states not yet field validated", "geometry_types": sorted({row['geometry_type'] for row in records}), "geometry_repair": "ST_MakeValid applied during persistence"})))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
                        (json.dumps({"persisted": inserted, "source_directory": str(source_dir.resolve())}), run_id))
        connection.commit()
        return {"run_id": str(run_id), "status": "completed", "dataset_key": DATASET_KEY, "features_upserted": inserted}
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status='partial',finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s",
                        (str(error)[:4000], json.dumps({"persisted_before_error": inserted}), run_id))
        connection.commit()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_local_flood_reference_ingest",))
        connection.commit()
