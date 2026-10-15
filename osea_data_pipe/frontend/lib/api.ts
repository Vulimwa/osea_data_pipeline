/** Client for Bravin's OSEAS read API (`/api/v1/oseas`). */

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
  checks?: {
    database?: { status?: string };
    inventory?: { status?: string };
    environmentalEvidence?: Record<string, number>;
    populationExposure?: { status?: string; assessmentRows?: number };
    latestFloodScreen?: { status?: string };
    [key: string]: unknown;
  };
};

export type LayerInfo = {
  layer?: string;
  endpoint?: string;
  status?: string;
  evidenceKind?: string;
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

export type GeoJsonCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id?: string;
    geometry: GeoJSON.Geometry | null;
    properties?: Record<string, unknown>;
  }>;
  status?: string;
  layer?: string;
};

export type ExposureRow = {
  hazard_type: string;
  exposure_status: string;
  assessment_period_start?: string | null;
  assessment_period_end?: string | null;
  evidence_kind?: string | null;
  provenance?: {
    exposure?: number | null;
    observed?: string;
    method?: string;
    source?: string;
    confidence_label?: string;
    pilot?: string;
  };
};

export type VulnerabilityRow = {
  status?: string;
  vulnerability_class?: string | null;
  score?: number | null;
  method?: string | null;
  missing_evidence?: unknown;
  provenance?: Record<string, unknown>;
};

export type CriticalityRow = {
  status?: string;
  score?: number | null;
  method?: string | null;
  evidence?: Record<string, unknown>;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text.slice(0, 240)}`);
  }
  return res.json() as Promise<T>;
}

export function bboxQuery(box = KANO_BBOX): string {
  return `${box.west},${box.south},${box.east},${box.north}`;
}

export function fetchReadiness() {
  return getJson<Readiness>('/readiness');
}

export function fetchLayers() {
  return getJson<{ data?: LayerInfo[]; layers?: LayerInfo[] } | LayerInfo[]>('/layers');
}

export async function fetchAssetsInBbox(
  limit = 500,
  opts?: { sourceDataset?: string; maxRows?: number },
) {
  const pages: AssetFeature[] = [];
  let offset = 0;
  let total = Infinity;
  const maxRows = opts?.maxRows ?? 5000;
  const dataset = opts?.sourceDataset
    ? `&sourceDataset=${encodeURIComponent(opts.sourceDataset)}`
    : '';
  while (offset < total && offset < maxRows) {
    const page = await getJson<AssetCollection>(
      `/assets?bbox=${bboxQuery()}&limit=${limit}&offset=${offset}${dataset}`,
    );
    pages.push(...(page.features ?? []));
    total = page.pagination?.total ?? pages.length;
    offset += limit;
    if (!(page.features?.length)) break;
  }
  return pages;
}

/** Pilot assets only — keep first paint fast (~2s). */
export function fetchPilotAssets() {
  return fetchAssetsInBbox(200, { sourceDataset: PILOT_DATASET, maxRows: 500 });
}

/** Optional other inventory in the bbox (slow; load only when layer is on). */
export function fetchInventorySample() {
  return fetchAssetsInBbox(100, { maxRows: 300 });
}

/** Soft timeout so a hung layer never blanks the shell. */
export function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), ms);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(fallback);
      });
  });
}

export function fetchHydrography() {
  return getJson<GeoJsonCollection>(
    `/layers/hydrography/geojson?bbox=${bboxQuery()}&limit=500`,
  );
}

export function fetchFloodReference() {
  return getJson<GeoJsonCollection>(
    `/layers/flood_reference/geojson?bbox=${bboxQuery()}&limit=200`,
  );
}

export function fetchAssetExposureLayer() {
  return getJson<GeoJsonCollection>(
    `/layers/asset_exposure/geojson?bbox=${bboxQuery()}&limit=500`,
  );
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

export function fetchAssetCriticality(id: string) {
  return getJson<{ assetId: string; status: string; data: CriticalityRow[] }>(
    `/assets/${id}/criticality`,
  );
}

export function pointCoords(geometry: GeoJSON.Geometry | null | undefined): [number, number] | null {
  if (!geometry) return null;
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

export function normalizeLayers(payload: unknown): LayerInfo[] {
  if (Array.isArray(payload)) return payload as LayerInfo[];
  if (payload && typeof payload === 'object') {
    const obj = payload as { data?: LayerInfo[]; layers?: LayerInfo[]; storedOutputs?: LayerInfo[] };
    return obj.data || obj.layers || obj.storedOutputs || [];
  }
  return [];
}
