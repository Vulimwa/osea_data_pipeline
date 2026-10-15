import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AssetMap, type MapLayers } from '../components/AssetMap';
import {
  PILOT_DATASET,
  type AssetFeature,
  fetchFloodReference,
  fetchHydrography,
  fetchInventorySample,
  fetchPilotAssets,
  withTimeout,
} from '../lib/api';

const defaultLayers: MapLayers = {
  pilot: true,
  inventory: false,
  hydrography: false,
  floodReference: false,
};

const emptyFc = { type: 'FeatureCollection' as const, features: [], status: 'not_assessed' };

export function MapPage() {
  const navigate = useNavigate();
  const [layers, setLayers] = useState<MapLayers>(defaultLayers);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [sheet, setSheet] = useState<'find' | 'layers' | null>(null);

  const pilotQ = useQuery({
    queryKey: ['assets-pilot'],
    queryFn: fetchPilotAssets,
    retry: 1,
  });

  const inventoryQ = useQuery({
    queryKey: ['assets-inventory'],
    queryFn: fetchInventorySample,
    enabled: layers.inventory,
    retry: 0,
  });

  const hydroQ = useQuery({
    queryKey: ['hydrography'],
    queryFn: () => withTimeout(fetchHydrography(), 10000, emptyFc),
    enabled: layers.hydrography,
    retry: 0,
  });

  const floodRefQ = useQuery({
    queryKey: ['flood-reference'],
    queryFn: () => withTimeout(fetchFloodReference(), 12000, emptyFc),
    enabled: layers.floodReference,
    retry: 0,
  });

  const assets = useMemo(() => {
    const byId = new Map<string, AssetFeature>();
    for (const feature of pilotQ.data ?? []) byId.set(feature.id, feature);
    if (layers.inventory) {
      for (const feature of inventoryQ.data ?? []) {
        if (feature.properties.sourceDataset !== PILOT_DATASET) byId.set(feature.id, feature);
      }
    }
    return [...byId.values()];
  }, [pilotQ.data, inventoryQ.data, layers.inventory]);

  const pilot = useMemo(() => {
    const q = query.trim().toLowerCase();
    return assets
      .filter((a) => a.properties.sourceDataset === PILOT_DATASET)
      .filter((a) => {
        if (!q) return true;
        const name = (a.properties.name || '').toLowerCase();
        const type = (a.properties.assetType || '').toLowerCase();
        return name.includes(q) || type.includes(q);
      })
      .sort((a, b) => (a.properties.name || a.id).localeCompare(b.properties.name || b.id));
  }, [assets, query]);

  const selected = assets.find((a) => a.id === selectedId) ?? null;

  const onToggleLayer = useCallback((key: keyof MapLayers) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const layerStatus = {
    hydrography: !layers.hydrography
      ? 'Off'
      : hydroQ.isLoading
        ? '…'
        : !(hydroQ.data?.features?.length)
          ? 'not assessed'
          : `${hydroQ.data?.features?.length ?? 0}`,
    floodReference: !layers.floodReference
      ? 'Off'
      : floodRefQ.isLoading
        ? '…'
        : !(floodRefQ.data?.features?.length)
          ? 'not assessed'
          : `${floodRefQ.data?.features?.length ?? 0}`,
  };

  return (
    <div className="map-page page">
      <div className="map-fill">
        <AssetMap
          assets={assets}
          hydrography={hydroQ.data ?? null}
          floodReference={floodRefQ.data ?? null}
          selectedId={selectedId}
          onSelect={setSelectedId}
          layers={layers}
        />
      </div>

      <div className="map-chrome top-left">
        <calcite-chip
          scale="s"
          kind="neutral"
          label={
            pilotQ.isLoading
              ? 'Nyando / Kano plains loading'
              : `Nyando / Kano plains · ${pilot.length} pilot`
          }
        >
          Nyando / Kano plains
          {pilotQ.isLoading ? ' · loading…' : ` · ${pilot.length} pilot`}
        </calcite-chip>
      </div>

      <div className="map-chrome top-right gap-2">
        <calcite-button
          appearance="solid"
          kind="neutral"
          icon-start="search"
          onClick={() => setSheet(sheet === 'find' ? null : 'find')}
        >
          Find
        </calcite-button>
        <calcite-button
          appearance="solid"
          kind="neutral"
          icon-start="layers"
          onClick={() => setSheet(sheet === 'layers' ? null : 'layers')}
        >
          Layers
        </calcite-button>
      </div>

      {sheet === 'layers' && (
        <div className="map-chrome sheet-anchor">
          <calcite-panel heading="Layers" closable oncalcitePanelClose={() => setSheet(null)}>
            <div className="sheet-body">
              {(
                [
                  ['pilot', 'Pilot assets', layers.pilot ? 'On' : 'Off'],
                  ['inventory', 'Other inventory', layers.inventory ? 'On' : 'Off'],
                  ['hydrography', 'Rivers / lakes', layerStatus.hydrography],
                  ['floodReference', 'Flood reference', layerStatus.floodReference],
                ] as const
              ).map(([key, label, status]) => (
                <calcite-label key={key} layout="inline" className="layer-row">
                  <calcite-switch
                    checked={layers[key] || undefined}
                    oncalciteSwitchChange={() => onToggleLayer(key)}
                  />
                  <span>
                    {label}
                    <small>{status}</small>
                  </span>
                </calcite-label>
              ))}
            </div>
          </calcite-panel>
        </div>
      )}

      {sheet === 'find' && (
        <div className="map-chrome sheet-anchor">
          <calcite-panel heading="Pilot assets" closable oncalcitePanelClose={() => setSheet(null)}>
            <div className="sheet-body">
              <calcite-input
                placeholder="Search by name"
                value={query}
                oncalciteInputInput={(e) => {
                  const target = e.target as HTMLElement & { value?: string };
                  setQuery(String(target.value ?? ''));
                }}
              />
              <calcite-list label="Pilot assets">
                {pilot.map((asset) => (
                  <calcite-list-item
                    key={asset.id}
                    label={asset.properties.name || 'Unnamed asset'}
                    description={asset.properties.assetType || 'asset'}
                    selected={asset.id === selectedId || undefined}
                    onClick={() => {
                      setSelectedId(asset.id);
                      setSheet(null);
                    }}
                  />
                ))}
              </calcite-list>
            </div>
          </calcite-panel>
        </div>
      )}

      {selected && (
        <div className="map-chrome bottom-left">
          <calcite-panel heading={selected.properties.name || 'Unnamed asset'}>
            <div slot="header-actions-end">
              <calcite-action icon="x" text="Clear" onClick={() => setSelectedId(null)} />
            </div>
            <div className="peek-body">
              <p>{selected.properties.assetType || 'asset'}</p>
              <calcite-button kind="brand" width="full" onClick={() => navigate(`/evidence/${selected.id}`)}>
                View evidence
              </calcite-button>
            </div>
          </calcite-panel>
        </div>
      )}
    </div>
  );
}
