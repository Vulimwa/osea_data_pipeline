/** Client for Bravin's OSEAS read API (`/api/v1/oseas`). */

export const API_BASE = '/api/v1/oseas';

/** Kano plains / Nyando pilot box from config/kenya_pilot.yaml */
export const KANO_BBOX = {
  west: 34.6,
  south: -0.4,
  east: 35.3,
  north: 0.1,
} as const;

export const KENYA_BBOX = {
  west: 33.9,
  south: -4.8,
  east: 41.9,
  north: 5.2,
} as const;

export type Bbox = { west: number; south: number; east: number; north: number };
export const PILOT_DATASET = 'osm_kano_pilot';

export type Readiness = {
  apiReadyForIntegration?: boolean;
  status?: string;
  checks?: {
    database?: { status?: string };
    inventory?: { status?: string };
    environmentalEvidence?: Record<
      string,
      { status?: string; dailyObservations?: number; activeDetectionPoints?: number; observationRows?: number }
    >;
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

export type RasterRegistryEntry = {
  key: string;
  name: string;
  provider: string | null;
  collectionId: string | null;
  accessMethod: string | null;
  retrievalStatus: string;
  layerType: 'raster';
  requiresCredentials: boolean;
  mapLayer: string | null;
  layerEndpoint: string | null;
  serviceUrl: string | null;
  spatialCoverage: string | null;
  temporalCoverage: string | null;
  resolutionM: number | null;
  units: Record<string, string> | null;
  bands: string[];
  purpose: string | null;
  style?: {
    min: number | null;
    max: number | null;
    palette: string[];
    valueType?: string;
    observationPeriod?: string | null;
    legendLabel?: string | null;
  } | null;
};

export type GeeMapLayer = {
  id: string;
  title: string;
  assetId: string;
  urlTemplate: string;
  opacity: number;
  minScale: number;
  maxScale: number;
  visible: boolean;
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
  pagination?: { total: number; limit: number; offset: number; returned?: number; truncated?: boolean };
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
  count?: number;
  pagination?: { total: number; limit: number; offset: number };
  dataStatus?: string;
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
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text.slice(0, 240);
    try {
      const payload = JSON.parse(text) as { message?: string; error?: string };
      detail = payload.message || payload.error || detail;
    } catch {
      // Keep the response excerpt when the API does not return JSON.
    }
    throw new Error(`${res.status} ${path}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function bboxQuery(box: Bbox = KANO_BBOX): string {
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
  opts?: { sourceDataset?: string; maxRows?: number; bbox?: Bbox },
) {
  const pages: AssetFeature[] = [];
  let offset = 0;
  let total = Infinity;
  const maxRows = opts?.maxRows ?? 5000;
  const box = opts?.bbox ?? KANO_BBOX;
  const dataset = opts?.sourceDataset
    ? `&sourceDataset=${encodeURIComponent(opts.sourceDataset)}`
    : '';
  while (offset < total && offset < maxRows) {
    const page = await getJson<AssetCollection>(
      `/assets?bbox=${bboxQuery(box)}&limit=${limit}&offset=${offset}${dataset}`,
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

export async function fetchAssetMapCollection(box: Bbox, sourceDataset?: string, maxRows = 2000) {
  const features: AssetFeature[] = [];
  const limit = 500;
  let offset = 0;
  let total = Infinity;
  let status: string | undefined;
  const dataset = sourceDataset ? `&sourceDataset=${encodeURIComponent(sourceDataset)}` : '';
  while (offset < total && offset < maxRows) {
    const page = await getJson<AssetCollection>(
      `/assets?bbox=${bboxQuery(box)}&limit=${limit}&offset=${offset}${dataset}`,
    );
    features.push(...(page.features ?? []));
    total = page.pagination?.total ?? features.length;
    status = page.status;
    offset += limit;
    if (!page.features?.length) break;
  }
  return {
    type: 'FeatureCollection' as const,
    features,
    status,
    pagination: {
      total: Number.isFinite(total) ? total : features.length,
      limit,
      offset: 0,
      returned: features.length,
      truncated: features.length < total,
    },
  };
}

export async function fetchGeoJsonLayer(
  layer: string,
  box: Bbox,
  options: { sourceDataset?: string; maxRows?: number } = {},
): Promise<GeoJsonCollection> {
  const maxRows = options.maxRows ?? 2000;
  const limit = 500;
  const features: GeoJsonCollection['features'] = [];
  let offset = 0;
  let total = Infinity;
  let firstResponse: GeoJsonCollection | null = null;
  const query = new URLSearchParams({ bbox: bboxQuery(box), limit: String(limit) });
  if (options.sourceDataset) query.set('sourceDataset', options.sourceDataset);
  while (offset < total && offset < maxRows) {
    query.set('offset', String(offset));
    const page = await getJson<GeoJsonCollection>(
      `/layers/${encodeURIComponent(layer)}/geojson?${query.toString()}`,
    );
    firstResponse ??= page;
    features.push(...(page.features ?? []));
    total = page.pagination?.total ?? page.count ?? features.length;
    offset += limit;
    if (!page.features?.length) break;
  }
  return {
    ...(firstResponse ?? { type: 'FeatureCollection' as const, features: [] }),
    features,
    count: features.length,
    pagination: {
      total: Number.isFinite(total) ? total : features.length,
      limit,
      offset: 0,
    },
  };
}

export async function fetchReferenceLayer(
  layer: 'flood_reference' | 'hydrography',
  box: Bbox,
  maxRows = 2000,
): Promise<GeoJsonCollection> {
  const limit = 500;
  const features: GeoJsonCollection['features'] = [];
  let offset = 0;
  let total = Infinity;
  let firstResponse: GeoJsonCollection | null = null;
  const query = new URLSearchParams({ bbox: bboxQuery(box), limit: String(limit) });
  while (offset < total && offset < maxRows) {
    query.set('offset', String(offset));
    const page = await getJson<GeoJsonCollection>(`/layers/${layer}/geojson?${query.toString()}`);
    firstResponse ??= page;
    features.push(...(page.features ?? []));
    total = page.pagination?.total ?? page.count ?? features.length;
    offset += limit;
    if (!page.features?.length) break;
  }
  return {
    ...(firstResponse ?? { type: 'FeatureCollection' as const, features: [] }),
    features,
    count: features.length,
    pagination: {
      total: Number.isFinite(total) ? total : features.length,
      limit,
      offset: 0,
    },
  };
}

export type AdministrativeSummary = {
  type: 'Feature';
  id: string;
  geometry: GeoJSON.Geometry;
  properties: Record<string, unknown> & {
    level?: 'ward' | 'county';
    name?: string | null;
    vulnerabilitySummary?: Record<string, unknown>;
  };
};

export function fetchAdministrativeSummary(
  level: 'ward' | 'county',
  unitId: string,
): Promise<AdministrativeSummary> {
  return getJson<AdministrativeSummary>(
    `/administrative/${level}/${encodeURIComponent(unitId)}/summary`,
  );
}

export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`API request timed out after ${ms / 1000} seconds`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
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

export function fetchPriorities() {
  return getJson<{ data?: Array<Record<string, unknown>>; status?: string }>('/priorities?limit=10');
}

export function fetchDatasetCatalog() {
  return getJson<{ data?: Array<Record<string, unknown>>; count?: number }>('/catalog');
}

export function fetchRasterRegistry() {
  return getJson<{ data?: RasterRegistryEntry[]; count?: number; source?: string }>('/raster-registry');
}

export function fetchGeeMapLayers() {
  return getJson<{ data?: GeeMapLayer[] }>('/gee-map-layers');
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

export function fetchAssetServiceDependencies(id: string) {
  return getJson<{ assetId: string; status: string; data: Array<Record<string, unknown>> }>(
    `/assets/${id}/service-dependencies`,
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
