/** Thin client for Bravin's OSEAS read API. */

export const API_BASE = '/api/v1/oseas';

/** Kano plains / Nyando pilot box from config/kenya_pilot.yaml */
export const KANO_BBOX = {
  west: 34.6,
  south: -0.4,
  east: 35.3,
  north: 0.1,
} as const;

export const PILOT_DATASET = 'osm_kano_pilot';

export type Readiness = {
  apiReadyForIntegration?: boolean;
  status?: string;
  checks?: Record<string, unknown>;
};

export type AssetProperties = {
  assetType?: string;
  name?: string | null;
  sourceDataset?: string;
  sourceFeatureId?: string;
  voltageKv?: number | null;
};

export type AssetFeature = {
  type: 'Feature';
  id: string;
  geometry: GeoJSON.Geometry;
  properties: AssetProperties;
};

export type AssetCollection = {
  type: 'FeatureCollection';
  features: AssetFeature[];
  pagination?: { total: number; limit: number; offset: number };
  status?: string;
};

export type ExposureRow = {
  hazard_type: string;
  exposure_status: string;
  assessment_period_start?: string | null;
  assessment_period_end?: string | null;
  provenance?: {
    exposure?: number | null;
    observed?: string;
    method?: string;
    source?: string;
    confidence_label?: string;
  };
};

export type VulnerabilityRow = {
  status?: string;
  vulnerability_class?: string | null;
  score?: number | null;
  method?: string | null;
  provenance?: Record<string, unknown>;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export function bboxQuery(box = KANO_BBOX): string {
  return `${box.west},${box.south},${box.east},${box.north}`;
}

export function fetchReadiness() {
  return getJson<Readiness>('/readiness');
}

export async function fetchAssetsInBbox(limit = 500) {
  const pages: AssetFeature[] = [];
  let offset = 0;
  let total = Infinity;
  while (offset < total && offset < 5000) {
    const page = await getJson<AssetCollection>(
      `/assets?bbox=${bboxQuery()}&limit=${limit}&offset=${offset}`,
    );
    pages.push(...(page.features ?? []));
    total = page.pagination?.total ?? pages.length;
    offset += limit;
    if (!(page.features?.length)) break;
  }
  return pages;
}

export function fetchAssetExposure(id: string) {
  return getJson<{ assetId: string; status: string; data: ExposureRow[] }>(
    `/assets/${id}/exposure`,
  );
}

export function fetchAssetVulnerability(id: string) {
  return getJson<{ assetId: string; status: string; data: VulnerabilityRow[] }>(
    `/assets/${id}/vulnerability`,
  );
}

export function pointCoords(geometry: GeoJSON.Geometry): [number, number] | null {
  if (geometry.type === 'Point') {
    const [lon, lat] = geometry.coordinates as [number, number];
    return [lon, lat];
  }
  if (geometry.type === 'MultiPoint' && geometry.coordinates[0]) {
    const [lon, lat] = geometry.coordinates[0] as [number, number];
    return [lon, lat];
  }
  return null;
}
