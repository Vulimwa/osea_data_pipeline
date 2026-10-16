import { useMemo, useState } from 'react';
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  AssetMap,
  type BasemapStyle,
  type MapOverlay,
  type SpatialResult,
} from '../components/AssetMap';
import {
  fetchAssetMapCollection,
  fetchGeoJsonLayer,
  fetchLayers,
  fetchPriorities,
  fetchRasterRegistry,
  fetchReadiness,
  fetchReferenceLayer,
  KANO_BBOX,
  KENYA_BBOX,
  PILOT_DATASET,
  type Bbox,
  type GeoJsonCollection,
  normalizeLayers,
  type Readiness,
} from '../lib/api';
import type { Theme } from '../lib/theme';

type Region = 'kenya' | 'kano';
type LayerId =
  | 'assets'
  | 'asset_exposure'
  | 'asset_vulnerability'
  | 'asset_criticality'
  | 'interventions'
  | 'prithvi_national_summaries'
  | 'vulnerability_summaries'
  | 'population_exposure'
  | 'fire'
  | 'flood_candidate'
  | 'flood_reference'
  | 'hydrography'
  | 'climate_observations'
  | 'rainfall'
  | 'nightlights';

type LayerDefinition = {
  id: LayerId;
  title: string;
  group: string;
  purpose: string;
  evidence: string;
  maxRows: number;
  getData: (bbox: Bbox, region: Region) => Promise<GeoJsonCollection>;
};

const layerDefinitions: LayerDefinition[] = [
  {
    id: 'assets',
    title: 'Energy infrastructure',
    group: 'Infrastructure',
    purpose: 'Power infrastructure from the canonical inventory.',
    evidence: 'Asset locations are not a reliability or outage assessment.',
    maxRows: 1000,
    getData: (bbox, region) =>
      fetchAssetMapCollection(bbox, region === 'kano' ? PILOT_DATASET : undefined, 1000),
  },
  {
    id: 'asset_exposure',
    title: 'Asset hazard exposure',
    group: 'Risk evidence',
    purpose: 'Recorded asset intersections with hazard evidence.',
    evidence: 'Exposure evidence is not a prediction of asset failure.',
    maxRows: 2000,
    getData: (bbox, region) =>
      fetchGeoJsonLayer('asset_exposure', bbox, {
        sourceDataset: region === 'kano' ? PILOT_DATASET : undefined,
        maxRows: 2000,
      }),
  },
  {
    id: 'asset_vulnerability',
    title: 'Asset vulnerability evidence',
    group: 'Risk evidence',
    purpose: 'Asset-level screening outputs and missing evidence.',
    evidence: 'Scores are interpreted with their scope and provenance.',
    maxRows: 2000,
    getData: (bbox, region) =>
      fetchGeoJsonLayer('asset_vulnerability', bbox, {
        sourceDataset: region === 'kano' ? PILOT_DATASET : undefined,
        maxRows: 2000,
      }),
  },
  {
    id: 'asset_criticality',
    title: 'Asset criticality',
    group: 'Decision context',
    purpose: 'Criticality assessments where recorded.',
    evidence: 'No criticality score is inferred from asset type alone.',
    maxRows: 1000,
    getData: (bbox, region) =>
      fetchGeoJsonLayer('asset_criticality', bbox, {
        sourceDataset: region === 'kano' ? PILOT_DATASET : undefined,
        maxRows: 1000,
      }),
  },
  {
    id: 'interventions',
    title: 'Intervention candidates',
    group: 'Decision context',
    purpose: 'Persisted intervention scenarios ready for review.',
    evidence: 'These are candidates, not approved investment decisions.',
    maxRows: 1000,
    getData: (bbox) => fetchGeoJsonLayer('interventions', bbox, { maxRows: 1000 }),
  },
  {
    id: 'prithvi_national_summaries',
    title: 'Prithvi flood candidates',
    group: 'Risk evidence',
    purpose: 'Nationwide tiled model candidate pixels summarized by ward/county.',
    evidence: 'Model candidates are not verified inundation or calibrated loss.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('prithvi_national_summaries', bbox, { maxRows: 2000 }),
  },
  {
    id: 'vulnerability_summaries',
    title: 'County & ward evidence',
    group: 'Decision context',
    purpose: 'Administrative vulnerability evidence and coverage context.',
    evidence: 'Composite scores are withheld where the evidence is incomplete.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('vulnerability_summaries', bbox, { maxRows: 2000 }),
  },
  {
    id: 'population_exposure',
    title: 'Population exposure',
    group: 'Decision context',
    purpose: 'Population potentially exposed in persisted assessments.',
    evidence: 'Potential exposure is not a count of people affected.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('population_exposure', bbox, { maxRows: 2000 }),
  },
  {
    id: 'fire',
    title: 'FIRMS fire detections',
    group: 'Hazards',
    purpose: 'Satellite fire detection points near infrastructure.',
    evidence: 'Detection points are not fire perimeters or damage reports.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('fire', bbox, { maxRows: 2000 }),
  },
  {
    id: 'flood_candidate',
    title: 'Flood screen candidates',
    group: 'Hazards',
    purpose: 'Most recent persisted flood screening features.',
    evidence: 'Screening candidates require verification before operational use.',
    maxRows: 1000,
    getData: (bbox) => fetchGeoJsonLayer('flood_candidate', bbox, { maxRows: 1000 }),
  },
  {
    id: 'flood_reference',
    title: 'Observed flood reference',
    group: 'Hazards',
    purpose: 'Historical/reference flood polygons retained with source provenance.',
    evidence: 'Reference events are not a forecast of future flooding.',
    maxRows: 2000,
    getData: (bbox) => fetchReferenceLayer('flood_reference', bbox, 2000),
  },
  {
    id: 'hydrography',
    title: 'Rivers & lakes',
    group: 'Context',
    purpose: 'Hydrography for geographic context.',
    evidence: 'Proximity to water alone does not establish flood risk.',
    maxRows: 2000,
    getData: (bbox) => fetchReferenceLayer('hydrography', bbox, 2000),
  },
  {
    id: 'climate_observations',
    title: 'Climate observations · incl. heat',
    group: 'Hazards',
    purpose: 'Persisted climate observations; inspect variable, unit, and source in each popup.',
    evidence: 'Coarse heat context is not a direct asset failure or outage prediction.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('climate_observations', bbox, { maxRows: 2000 }),
  },
  {
    id: 'rainfall',
    title: 'Rainfall anomalies',
    group: 'Hazards',
    purpose: 'Persisted CHIRPS rainfall indicators where available.',
    evidence: 'Rainfall anomaly is not a direct flood extent.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('rainfall', bbox, { maxRows: 2000 }),
  },
  {
    id: 'nightlights',
    title: 'Night-time lights',
    group: 'Decision context',
    purpose: 'Night-light observations used as a service-context proxy.',
    evidence: 'Radiance is not an outage measurement or electricity-access estimate.',
    maxRows: 2000,
    getData: (bbox) => fetchGeoJsonLayer('nightlights', bbox, { maxRows: 2000 }),
  },
];

const defaultVisible: LayerId[] = [
  'assets',
  'asset_exposure',
  'asset_vulnerability',
  'vulnerability_summaries',
  'prithvi_national_summaries',
];
const defaultEmptyCollection: GeoJsonCollection = {
  type: 'FeatureCollection',
  features: [],
  status: 'not_assessed',
};

function countLabel(value: unknown): string {
  const count = Number(value);
  return Number.isFinite(count) ? count.toLocaleString() : '—';
}

function statusText(value: unknown): string {
  if (value == null || value === '') return 'not assessed';
  return String(value).replaceAll('_', ' ');
}

function inputValue(event: Event): string {
  return String((event.target as HTMLElement & { value?: string }).value ?? '');
}

export function MapPage() {
  const navigate = useNavigate();
  const { theme } = useOutletContext<{ theme: Theme }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [region, setRegion] = useState<Region>(() =>
    searchParams.get('area') === 'kenya' ? 'kenya' : 'kano',
  );
  const [basemapStyle, setBasemapStyle] = useState<BasemapStyle>('theme');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState<LayerId[]>(defaultVisible);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [drawAreaRequest, setDrawAreaRequest] = useState(0);
  const [clearAreaRequest, setClearAreaRequest] = useState(0);
  const [spatialResults, setSpatialResults] = useState<SpatialResult[] | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const bbox = region === 'kano' ? KANO_BBOX : KENYA_BBOX;

  const readinessQ = useQuery({
    queryKey: ['readiness'],
    queryFn: fetchReadiness,
    retry: 0,
  });
  const apiLayersQ = useQuery({ queryKey: ['api-layers'], queryFn: fetchLayers, retry: 0 });
  const rasterRegistryQ = useQuery({
    queryKey: ['raster-registry'],
    queryFn: fetchRasterRegistry,
    retry: 0,
  });
  const prioritiesQ = useQuery({
    queryKey: ['priorities'],
    queryFn: fetchPriorities,
    retry: 0,
  });

  const layerQueries = useQueries({
    queries: layerDefinitions.map((layer) => ({
      queryKey: ['map-layer', region, layer.id],
      queryFn: () => layer.getData(bbox, region),
      enabled: visibleLayers.includes(layer.id),
      retry: 0,
      staleTime: 5 * 60 * 1000,
    })),
  });
  const queryById = useMemo(
    () => new Map(layerDefinitions.map((layer, index) => [layer.id, layerQueries[index]])),
    [layerQueries],
  );
  const overlays: MapOverlay[] = visibleLayers.map((id) => {
    const definition = layerDefinitions.find((layer) => layer.id === id);
    const result = queryById.get(id);
    return {
      id,
      title: definition?.title ?? id,
      collection: (result?.data as GeoJsonCollection | undefined) ?? null,
      visible: true,
    };
  });
  const visibleAssets = (queryById.get('assets')?.data as GeoJsonCollection | undefined)?.features ?? [];
  const filteredAssets = visibleAssets.filter((feature) => {
    if (!search.trim()) return true;
    const properties = feature.properties ?? {};
    const haystack = [properties.name, properties.assetType, properties.sourceDataset]
      .map((value) => String(value ?? '').toLowerCase())
      .join(' ');
    return haystack.includes(search.trim().toLowerCase());
  });
  const selectedFeature = visibleAssets.find((feature) => String(feature.id) === selectedId);
  const currentAssetLayer = queryById.get('assets')?.data as
    | (GeoJsonCollection & { pagination?: { total: number; returned?: number; truncated?: boolean } })
    | undefined;
  const currentExposure = queryById.get('asset_exposure')?.data as GeoJsonCollection | undefined;
  const apiError = [
    readinessQ.error,
    apiLayersQ.error,
    rasterRegistryQ.error,
    prioritiesQ.error,
    ...layerQueries.filter((query) => query.isError).map((query) => query.error),
  ].find(Boolean);
  const storedLayers = normalizeLayers(apiLayersQ.data);
  const rasterEntries = rasterRegistryQ.data?.data ?? [];
  const readiness = readinessQ.data;
  const checks = readiness?.checks;
  const environmentEvidence = checks?.environmentalEvidence ?? {};
  const prithvi = checks?.prithviNational as Record<string, unknown> | undefined;
  const assetLayerStatus = queryById.get('assets');

  const toggleLayer = (id: LayerId) => {
    setVisibleLayers((current) =>
      current.includes(id) ? current.filter((layer) => layer !== id) : [...current, id],
    );
  };
  const goToEvidence = () => {
    if (!selectedFeature || !selectedId) return;
    navigate(`/evidence/${selectedId}`, { state: { asset: selectedFeature } });
  };
  const groups = [...new Set(layerDefinitions.map((layer) => layer.group))];
  const selectedAssetType = String(selectedFeature?.properties?.assetType ?? 'Energy asset');
  const serverLayer = (id: LayerId) => storedLayers.find((layer) => layer.layer === id);
  const rasterSummary = rasterEntries.length
    ? `${rasterEntries.length.toLocaleString()} registered raster sources`
    : 'No registered rasters';

  return (
    <main className="risk-map-page">
      <div className="risk-map-canvas">
        <AssetMap
          overlays={overlays}
          selectedId={selectedId}
          region={region}
          theme={theme}
          basemapStyle={basemapStyle}
          drawAreaRequest={drawAreaRequest}
          clearAreaRequest={clearAreaRequest}
          onSelect={setSelectedId}
          onExploreAssetEvidence={(assetId) => navigate(`/evidence/${assetId}`)}
          onExploreAreaEvidence={(level, unitId) =>
            navigate(`/evidence/area/${level}/${encodeURIComponent(unitId)}`)
          }
          onAreaResult={setSpatialResults}
          onMapError={setMapError}
        />
      </div>

      <div className={`risk-map-header${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
        <div className="map-heading">
          <calcite-chip label="Climate and power" scale="s" kind="brand" icon="analysis">
            CLIMATE × POWER
          </calcite-chip>
          <span>{region === 'kenya' ? 'Kenya-wide view' : 'Kano Plains demo'}</span>
        </div>
        <div className="map-header-tools">
          <calcite-button
            appearance="outline"
            kind="neutral"
            scale="s"
            icon-start={sidebarOpen ? 'chevron-left' : 'chevron-right'}
            aria-label={sidebarOpen ? 'Collapse map controls' : 'Expand map controls'}
            onClick={() => setSidebarOpen((open) => !open)}
          >
            {sidebarOpen ? 'Hide controls' : 'Show controls'}
          </calcite-button>
          <calcite-select
            label="Analysis area"
            scale="s"
            value={region}
            oncalciteSelectChange={(event) => {
              const nextRegion = inputValue(event) === 'kano' ? 'kano' : 'kenya';
              setRegion(nextRegion);
              setSearchParams({ area: nextRegion });
              setSelectedId(null);
              setSpatialResults(null);
            }}
          >
            <calcite-option value="kenya">Nationwide · Kenya</calcite-option>
            <calcite-option value="kano">Demo · Kano Plains</calcite-option>
          </calcite-select>
          <calcite-select
            label="Basemap"
            scale="s"
            value={basemapStyle}
            oncalciteSelectChange={(event) => {
              const style = inputValue(event);
              if (
                style === 'theme' ||
                style === 'streets-vector' ||
                style === 'satellite' ||
                style === 'topo-vector'
              ) {
                setBasemapStyle(style);
              }
            }}
          >
            <calcite-option value="theme">OpenStreetMap</calcite-option>
            <calcite-option value="streets-vector">Streets</calcite-option>
            <calcite-option value="satellite">Imagery</calcite-option>
            <calcite-option value="topo-vector">Topographic</calcite-option>
          </calcite-select>
          <calcite-button
            appearance="solid"
            kind="neutral"
            scale="s"
            icon-start="polygon"
            onClick={() => setDrawAreaRequest((n) => n + 1)}
          >
            Draw an area
          </calcite-button>
          {spatialResults && (
            <calcite-button
              appearance="outline"
              kind="neutral"
              scale="s"
              icon-start="reset"
              onClick={() => setClearAreaRequest((n) => n + 1)}
            >
              Clear scan
            </calcite-button>
          )}
        </div>
      </div>

      {sidebarOpen && (
        <aside className="risk-map-sidebar">
          <calcite-panel className="risk-panel" heading="Map controls">
            <div className="risk-panel-body">
              <div className="risk-intro">
                <calcite-chip
                  label={readinessQ.isLoading ? 'Connecting to OSEAS API' : statusText(readiness?.status)}
                  scale="s"
                  kind={readiness?.apiReadyForIntegration ? 'brand' : 'neutral'}
                  icon={readiness?.apiReadyForIntegration ? 'check' : 'information'}
                >
                  {readinessQ.isLoading ? 'Connecting to OSEAS API' : statusText(readiness?.status)}
                </calcite-chip>
              </div>

            <div className="risk-metrics">
              <calcite-block heading="Assets">
                <strong>{countLabel(currentAssetLayer?.pagination?.total)}</strong>
                <span>
                  {assetLayerStatus?.isFetching
                    ? 'Loading assets…'
                    : `${countLabel(currentAssetLayer?.pagination?.returned ?? visibleAssets.length)} rendered`}
                </span>
              </calcite-block>
              <calcite-block heading="Exposure records">
                <strong>{countLabel(currentExposure?.features.length)}</strong>
                <span>
                  {queryById.get('asset_exposure')?.isFetching
                    ? 'Loading exposure…'
                    : currentExposure?.features.length
                      ? 'Asset-linked records'
                      : 'No records in this view'}
                </span>
              </calcite-block>
              <calcite-block heading="Raster registry">
                <strong>{rasterEntries.length ? countLabel(rasterEntries.length) : '0'}</strong>
                <span>
                  {rasterRegistryQ.isLoading
                    ? 'Loading raster registry…'
                    : rasterSummary}
                </span>
              </calcite-block>
            </div>

            {apiError && (
              <calcite-notice open kind="danger" icon>
                <div slot="title">OSEAS API request failed</div>
                <div slot="message">
                  {apiError instanceof Error ? apiError.message : 'The API returned an error.'}
                </div>
              </calcite-notice>
            )}
            {mapError && (
              <calcite-notice open kind="danger" icon>
                <div slot="title">Map operation failed</div>
                <div slot="message">{mapError}</div>
                <calcite-action slot="actions-end" icon="x" text="Dismiss" onClick={() => setMapError(null)} />
              </calcite-notice>
            )}

            <calcite-block heading="Evidence layers" open>
              <div className="layer-groups">
                {groups.map((group) => (
                  <section className="layer-group" key={group}>
                    <h3>{group}</h3>
                    {layerDefinitions
                      .filter((layer) => layer.group === group)
                      .map((layer) => {
                        const query = queryById.get(layer.id);
                        const data = query?.data as GeoJsonCollection | undefined;
                        const serverInfo = serverLayer(layer.id);
                        const loading = query?.isFetching;
                        const rowStatus = query?.isError
                          ? 'Error'
                          : loading
                            ? 'Loading'
                            : data?.features.length
                              ? `${data.features.length.toLocaleString()} features`
                              : serverInfo?.status === 'not_assessed'
                                ? 'Not assessed'
                                : data
                                  ? 'No records'
                                  : serverInfo?.status || 'On demand';
                        return (
                          <calcite-label className="layer-toggle" key={layer.id}>
                            <span className="layer-label">
                              <span>{layer.title}</span>
                              <small>{rowStatus}</small>
                            </span>
                            {loading && <calcite-loader label="Loading layer" scale="s" />}
                            <calcite-switch
                              checked={visibleLayers.includes(layer.id) || undefined}
                              label={layer.title}
                              oncalciteSwitchChange={() => toggleLayer(layer.id)}
                            />
                          </calcite-label>
                        );
                      })}
                  </section>
                ))}
              </div>
            </calcite-block>

            {rasterEntries.length > 0 && (
              <calcite-block heading="Registered rasters" open>
                <div className="raster-legend-stack">
                  {rasterEntries.slice(0, 7).map((entry) => {
                    const unitText = Object.values(entry.units ?? {}).filter(Boolean).join(', ') || '—';
                    const palette = entry.style?.palette ?? [];
                    return (
                      <div key={entry.key} className="raster-legend-card">
                        <div className="raster-legend-header">
                          <strong>{entry.name}</strong>
                          <span>{entry.retrievalStatus.replaceAll('_', ' ')}</span>
                        </div>
                        {palette.length > 0 && (
                          <div className="raster-legend-swatches" aria-label={`${entry.name} legend`}>
                            {palette.map((color) => (
                              <span key={`${entry.key}-${color}`} style={{ background: color }} />
                            ))}
                          </div>
                        )}
                        <div className="raster-legend-meta">
                          <span>Unit</span>
                          <strong>{unitText}</strong>
                        </div>
                        <div className="raster-legend-meta">
                          <span>Period</span>
                          <strong>{entry.style?.observationPeriod ?? entry.temporalCoverage ?? 'Not specified'}</strong>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </calcite-block>
            )}

            <calcite-block heading="Area scan">
              <calcite-button
                width="full"
                appearance="outline"
                kind="neutral"
                icon-start="polygon"
                onClick={() => setDrawAreaRequest((n) => n + 1)}
              >
                Draw AOI & count intersections
              </calcite-button>
              {spatialResults && (
                <div className="spatial-results">
                  {spatialResults.map((result) => (
                    <div className="spatial-result" key={result.layerId}>
                      <span>{result.title}</span>
                      <strong>{result.intersectingFeatures.toLocaleString()}</strong>
                    </div>
                  ))}
                  <calcite-notice open kind="warning" icon>
                    <div slot="message">
                      Counts cover features loaded in this view only.
                    </div>
                  </calcite-notice>
                </div>
              )}
            </calcite-block>

            <calcite-block heading="Evidence coverage">
              <div className="signal-list">
                <div>
                  <span>Prithvi national run</span>
                  <strong>{statusText(prithvi?.status)}</strong>
                </div>
                <div>
                  <span>Heat observations</span>
                  <strong>
                    {countLabel(environmentEvidence.heat?.dailyObservations)}
                  </strong>
                </div>
                <div>
                  <span>Fire detections</span>
                  <strong>
                    {countLabel(environmentEvidence.fire?.activeDetectionPoints)}
                  </strong>
                </div>
                <div>
                  <span>Population exposure</span>
                  <strong>{statusText(checks?.populationExposure?.status)}</strong>
                </div>
              </div>
              <p className="evidence-caveat">
                Model candidates need verification. Missing evidence is not zero risk.
              </p>
            </calcite-block>

            <calcite-block heading="Suggested actions">
              {prioritiesQ.isLoading ? (
                <calcite-loader label="Loading priorities" />
              ) : prioritiesQ.data?.data?.length ? (
                <calcite-list label="Suggested interventions">
                  {prioritiesQ.data.data.slice(0, 5).map((item, index) => (
                    <calcite-list-item
                      key={String(item.id ?? index)}
                      label={String(item.action ?? 'Review candidate')}
                      description={`${statusText(item.priority)} priority · ${String(item.reason ?? 'Evidence-linked candidate')}`}
                    />
                  ))}
                </calcite-list>
              ) : (
                <calcite-notice open kind="info" icon>
                  <div slot="message">
                    No persisted candidates.
                  </div>
                </calcite-notice>
              )}
            </calcite-block>

              {selectedFeature && (
                <calcite-block
                  heading={String(selectedFeature.properties?.name ?? 'Selected energy asset')}
                  description={selectedAssetType}
                  open
                >
                  <calcite-button
                    width="full"
                    kind="brand"
                    icon-start="launch"
                    onClick={goToEvidence}
                  >
                    Open asset evidence
                  </calcite-button>
                </calcite-block>
              )}
            </div>
          </calcite-panel>
        </aside>
      )}

      <div className="map-search-tools">
        <calcite-input
          placeholder={region === 'kano' ? 'Find a Kano pilot asset' : 'Find in loaded energy assets'}
          icon="search"
          clearable
          value={search}
          oncalciteInputInput={(event) => setSearch(inputValue(event))}
        />
        {search && (
          <calcite-list label="Asset search results" className="map-search-results">
            {filteredAssets.slice(0, 12).map((feature) => (
              <calcite-list-item
                key={String(feature.id)}
                label={String(feature.properties?.name ?? 'Unnamed asset')}
                description={String(feature.properties?.assetType ?? 'Energy asset')}
                onClick={() => setSelectedId(String(feature.id))}
              />
            ))}
          </calcite-list>
        )}
      </div>

      <div className="map-attribution-note">
        <calcite-chip
          label={region === 'kano' ? 'Kano pilot · not national evidence' : 'National view · evidence varies by layer'}
          scale="s"
          kind="neutral"
          icon="information"
        >
          {region === 'kano' ? 'Kano pilot · not national evidence' : 'National view · evidence varies by layer'}
        </calcite-chip>
      </div>
    </main>
  );
}
