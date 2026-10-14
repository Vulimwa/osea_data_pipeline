"""PostGIS operations shared by OSEAS hazard processing and boundary refreshes."""

from __future__ import annotations

from typing import Any


def refresh_asset_admin_assignments(cur: Any, processing_run_id: str) -> int:
    """Assign points by polygon coverage and clip lines/polygons to admin units."""
    cur.execute("UPDATE asset_admin_assignments SET is_current=FALSE WHERE is_current=TRUE")
    cur.execute(
        """WITH point_candidates AS (
             SELECT a.id AS asset_id,u.id AS unit_id,u.unit_level,
                    row_number() OVER (PARTITION BY a.id,u.unit_level ORDER BY ST_Area(u.geom::geography),u.stable_code NULLS LAST,u.id) AS rank
             FROM energy_assets a JOIN administrative_units u
               ON u.unit_level IN ('ward','county') AND ST_Covers(u.geom,a.geom)
             WHERE ST_GeometryType(a.geom) IN ('ST_Point','ST_MultiPoint')
           ), point_rows AS (
             SELECT asset_id,unit_id,unit_level,'point_covered_by'::text AS method,NULL::double precision AS line_m,NULL::double precision AS area_m2
             FROM point_candidates WHERE rank=1
           ), area_candidates AS (
             SELECT a.id AS asset_id,u.id AS unit_id,u.unit_level,
               CASE WHEN ST_Dimension(a.geom)=1 THEN ST_Length(ST_CollectionExtract(ST_Intersection(a.geom,u.geom),2)::geography) END AS line_m,
               CASE WHEN ST_Dimension(a.geom)=2 THEN ST_Area(ST_Intersection(a.geom,u.geom)::geography) END AS area_m2
             FROM energy_assets a JOIN administrative_units u
               ON u.unit_level IN ('ward','county') AND ST_Intersects(a.geom,u.geom)
             WHERE ST_GeometryType(a.geom) NOT IN ('ST_Point','ST_MultiPoint')
           ), area_rows AS (
             SELECT asset_id,unit_id,unit_level,'boundary_intersection'::text AS method,line_m,area_m2
             FROM area_candidates WHERE COALESCE(line_m,area_m2,0)>0.01
           ), all_rows AS (
             SELECT * FROM point_rows UNION ALL SELECT * FROM area_rows
           )
           INSERT INTO asset_admin_assignments
             (id,energy_asset_id,administrative_unit_id,unit_level,relation_method,intersection_length_m,intersection_area_m2,processing_run_id,updated_at)
           SELECT md5(asset_id::text || ':' || unit_id::text)::uuid,asset_id,unit_id,unit_level,method,line_m,area_m2,%s,NOW()
           FROM all_rows
           ON CONFLICT (energy_asset_id,administrative_unit_id) DO UPDATE SET
             unit_level=EXCLUDED.unit_level,relation_method=EXCLUDED.relation_method,
             intersection_length_m=EXCLUDED.intersection_length_m,intersection_area_m2=EXCLUDED.intersection_area_m2,
             processing_run_id=EXCLUDED.processing_run_id,is_current=TRUE,updated_at=NOW()""",
        (processing_run_id,),
    )
    return cur.rowcount


def refresh_asset_admin_assignment_batch(cur: Any, processing_run_id: str, asset_ids: list[str]) -> int:
    """Upsert ward/county memberships for a bounded list of asset UUIDs."""
    if not asset_ids:
        return 0
    cur.execute(
        """WITH batch_assets AS MATERIALIZED (
             SELECT id,geom FROM energy_assets WHERE id=ANY(%s::uuid[])
           ), point_candidates AS (
             SELECT a.id AS asset_id,u.id AS unit_id,u.unit_level,
                    row_number() OVER (PARTITION BY a.id,u.unit_level ORDER BY ST_Area(u.geom::geography),u.stable_code NULLS LAST,u.id) AS rank
             FROM batch_assets a JOIN administrative_units u
               ON u.unit_level IN ('ward','county') AND ST_Covers(u.geom,a.geom)
             WHERE ST_GeometryType(a.geom) IN ('ST_Point','ST_MultiPoint')
           ), point_rows AS (
             SELECT asset_id,unit_id,unit_level,'point_covered_by'::text AS method,
                    NULL::double precision AS line_m,NULL::double precision AS area_m2
             FROM point_candidates WHERE rank=1
           ), area_candidates AS (
             SELECT a.id AS asset_id,u.id AS unit_id,u.unit_level,
               CASE WHEN ST_Dimension(a.geom)=1 THEN ST_Length(ST_CollectionExtract(ST_Intersection(a.geom,u.geom),2)::geography) END AS line_m,
               CASE WHEN ST_Dimension(a.geom)=2 THEN ST_Area(ST_Intersection(a.geom,u.geom)::geography) END AS area_m2
             FROM batch_assets a JOIN administrative_units u
               ON u.unit_level IN ('ward','county') AND ST_Intersects(a.geom,u.geom)
             WHERE ST_GeometryType(a.geom) NOT IN ('ST_Point','ST_MultiPoint')
           ), area_rows AS (
             SELECT asset_id,unit_id,unit_level,'boundary_intersection'::text AS method,line_m,area_m2
             FROM area_candidates WHERE COALESCE(line_m,area_m2,0)>0.01
           ), all_rows AS (
             SELECT * FROM point_rows UNION ALL SELECT * FROM area_rows
           )
           INSERT INTO asset_admin_assignments
             (id,energy_asset_id,administrative_unit_id,unit_level,relation_method,intersection_length_m,intersection_area_m2,processing_run_id,updated_at)
           SELECT md5(asset_id::text || ':' || unit_id::text)::uuid,asset_id,unit_id,unit_level,method,line_m,area_m2,%s,NOW()
           FROM all_rows
           ON CONFLICT (energy_asset_id,administrative_unit_id) DO UPDATE SET
             unit_level=EXCLUDED.unit_level,relation_method=EXCLUDED.relation_method,
             intersection_length_m=EXCLUDED.intersection_length_m,intersection_area_m2=EXCLUDED.intersection_area_m2,
             processing_run_id=EXCLUDED.processing_run_id,is_current=TRUE,updated_at=NOW()""",
        (asset_ids, processing_run_id),
    )
    return cur.rowcount
