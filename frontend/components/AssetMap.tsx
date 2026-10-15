import { useEffect, useRef } from 'react';
import ArcGISMap from '@arcgis/core/Map';
import MapView from '@arcgis/core/views/MapView';
import GraphicsLayer from '@arcgis/core/layers/GraphicsLayer';
import Graphic from '@arcgis/core/Graphic';
import Point from '@arcgis/core/geometry/Point';
import Polyline from '@arcgis/core/geometry/Polyline';
import Polygon from '@arcgis/core/geometry/Polygon';
import Extent from '@arcgis/core/geometry/Extent';
import Basemap from '@arcgis/core/Basemap';
import TileLayer from '@arcgis/core/layers/TileLayer';
import SketchViewModel from '@arcgis/core/widgets/Sketch/SketchViewModel';
import PopupTemplate from '@arcgis/core/PopupTemplate';
import * as geometryEngine from '@arcgis/core/geometry/geometryEngine';
import SimpleMarkerSymbol from '@arcgis/core/symbols/SimpleMarkerSymbol';
import SimpleLineSymbol from '@arcgis/core/symbols/SimpleLineSymbol';
import SimpleFillSymbol from '@arcgis/core/symbols/SimpleFillSymbol';
import type { Bbox, GeoJsonCollection } from '../lib/api';
import { KANO_BBOX, KENYA_BBOX, pointCoords } from '../lib/api';
import type { Theme } from '../lib/theme';

export type MapOverlay = {
  id: string;
  title: string;
  collection: GeoJsonCollection | null;
  visible: boolean;
};

export type SpatialResult = {
  layerId: string;
  title: string;
  intersectingFeatures: number;
  returnedFeatures: number;
};

type Props = {
  overlays: MapOverlay[];
  selectedId: string | null;
  region: 'kenya' | 'kano';
  theme: Theme;
  basemapStyle: BasemapStyle;
  drawAreaRequest: number;
  clearAreaRequest: number;
  onSelect: (id: string) => void;
  onAreaResult: (results: SpatialResult[] | null) => void;
  onMapError: (message: string | null) => void;
};

type OverlayLayers = Map<string, GraphicsLayer>;
export type BasemapStyle = 'theme' | 'streets-vector' | 'satellite' | 'topo-vector';

function mapExtent(box: Bbox) {
  return new Extent({
    xmin: box.west,
    ymin: box.south,
    xmax: box.east,
    ymax: box.north,
    spatialReference: { wkid: 4326 },
  });
}

function mapBasemap(theme: Theme, style: BasemapStyle) {
  if (style !== 'theme') return Basemap.fromId(style) ?? mapBasemap(theme, 'theme');
  const prefix = 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  const variant = theme === 'light' ? 'World_Light_Gray' : 'World_Dark_Gray';
  return new Basemap({
    baseLayers: [
      new TileLayer({ url: `${prefix}${variant}_Base/MapServer` }),
      new TileLayer({ url: `${prefix}${variant}_Reference/MapServer` }),
    ],
  });
}

function geometryFromGeoJson(geometry: GeoJSON.Geometry | null | undefined) {
  if (!geometry) return null;
  if (geometry.type === 'Point') {
    const [x, y] = geometry.coordinates as [number, number];
    return new Point({ x, y, spatialReference: { wkid: 4326 } });
  }
  if (geometry.type === 'MultiPoint') {
    const [x, y] = (geometry.coordinates[0] as [number, number]) || [];
    if (x == null) return null;
    return new Point({ x, y, spatialReference: { wkid: 4326 } });
  }
  if (geometry.type === 'LineString') {
    return new Polyline({
      paths: [geometry.coordinates as number[][]],
      spatialReference: { wkid: 4326 },
    });
  }
  if (geometry.type === 'MultiLineString') {
    return new Polyline({
      paths: geometry.coordinates as number[][][],
      spatialReference: { wkid: 4326 },
    });
  }
  if (geometry.type === 'Polygon') {
    return new Polygon({
      rings: geometry.coordinates as number[][][],
      spatialReference: { wkid: 4326 },
    });
  }
  if (geometry.type === 'MultiPolygon') {
    const rings = (geometry.coordinates as number[][][][]).flat();
    return new Polygon({ rings, spatialReference: { wkid: 4326 } });
  }
  return null;
}

function valueForPopup(value: unknown): string | number | boolean | null {
  if (value == null || ['string', 'number', 'boolean'].includes(typeof value)) {
    return value as string | number | boolean | null;
  }
  if (Array.isArray(value)) return JSON.stringify(value).slice(0, 400);
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 600);
  return String(value);
}

function popupKey(key: string) {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]/g, ' ').trim().toLowerCase();
}

function popupValue(value: unknown) {
  const primitive = valueForPopup(value);
  if (primitive == null) return '';
  if (typeof primitive === 'boolean') return primitive ? 'Yes' : 'No';
  const text = String(primitive).replace(/_/g, ' ').trim();
  return text.length > 96 ? `${text.slice(0, 93)}…` : text;
}

function makePopup(title: string, properties: Record<string, unknown>) {
  const attributes: Record<string, string | number | boolean | null> = {};
  for (const [key, value] of Object.entries(properties)) {
    attributes[key] = valueForPopup(value);
  }
  const preferredKeys = [
    'assetType',
    'hazardType',
    'exposureStatus',
    'vulnerabilityClass',
    'vulnerabilityScore',
    'criticalityScore',
    'riskScore',
    'confidence',
    'status',
    'sourceDataset',
    'assessmentPeriod',
    'assessmentPeriodStart',
    'assessmentPeriodEnd',
  ];
  const byNormalizedKey = new Map(
    Object.keys(properties).map((key) => [key.toLowerCase().replace(/[^a-z0-9]/g, ''), key]),
  );
  const selectedKeys = preferredKeys
    .map((key) => byNormalizedKey.get(key.toLowerCase()))
    .filter((key): key is string => Boolean(key));
  const relevantKeys = Object.keys(properties).filter((key) =>
    /asset.?type|hazard|exposure|vulnerab|critical|risk|resilien|reliab|confidence|assessment|period|source|status|county|ward/i.test(
      key,
    ),
  );
  const descriptorKey = ['assetType', 'asset_type', 'hazardType', 'hazard_type']
    .map((key) => byNormalizedKey.get(key.toLowerCase()))
    .find((key) => key != null);
  const factKeys = [...new Set([...selectedKeys, ...relevantKeys])]
    .filter((key) => key !== descriptorKey && !key.startsWith('__') && popupValue(properties[key]) !== '')
    .slice(0, 4);
  const content = document.createElement('div');
  content.className = 'oseas-feature-popup';
  const descriptor = properties.assetType ?? properties.asset_type ?? properties.hazardType ?? properties.hazard_type;
  if (descriptor != null && String(descriptor).trim()) {
    const chip = document.createElement('calcite-chip');
    chip.setAttribute('scale', 's');
    chip.textContent = popupValue(descriptor);
    content.append(chip);
  }
  if (factKeys.length) {
    const facts = document.createElement('div');
    facts.className = 'oseas-popup-facts';
    for (const key of factKeys) {
      const value = popupValue(properties[key]);
      if (!value) continue;
      const item = document.createElement('div');
      item.className = 'oseas-popup-fact';
      const label = document.createElement('span');
      label.textContent = popupKey(key);
      const detail = document.createElement('strong');
      detail.textContent = value;
      item.append(label, detail);
      facts.append(item);
    }
    content.append(facts);
  } else {
    const message = document.createElement('p');
    message.className = 'oseas-popup-empty';
    message.textContent = 'No additional evidence is recorded for this feature.';
    content.append(message);
  }
  return {
    attributes,
    popupTemplate: new PopupTemplate({
      title,
      content,
    }),
  };
}

function symbolFor(
  layerId: string,
  properties: Record<string, unknown>,
  selected: boolean,
  geometry: GeoJSON.Geometry,
) {
  if (geometry.type === 'LineString' || geometry.type === 'MultiLineString') {
    if (layerId === 'hydrography') {
      return new SimpleLineSymbol({ color: [86, 168, 206, 0.9], width: 1.5 });
    }
    return new SimpleLineSymbol({
      color: layerId === 'asset_exposure' ? [240, 132, 66, 0.95] : [82, 179, 174, 0.85],
      width: selected ? 3 : 1.5,
    });
  }
  if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
    if (layerId === 'flood_reference' || layerId === 'flood_candidate') {
      return new SimpleFillSymbol({
        color: [230, 99, 51, 0.24],
        outline: { color: [245, 145, 88, 0.9], width: 1.2 },
      });
    }
    if (layerId === 'population_exposure') {
      return new SimpleFillSymbol({
        color: [162, 130, 219, 0.2],
        outline: { color: [193, 169, 235, 0.8], width: 1 },
      });
    }
    if (['prithvi_national_summaries', 'administrative_summaries', 'vulnerability_summaries'].includes(layerId)) {
      const hasCandidates = Number(properties.candidateFraction ?? properties.candidateExposureFraction ?? 0) > 0;
      return new SimpleFillSymbol({
        color: hasCandidates ? [224, 107, 45, 0.26] : [142, 151, 164, 0.12],
        outline: {
          color: hasCandidates ? [240, 164, 106, 0.95] : [179, 188, 199, 0.65],
          width: 0.8,
        },
      });
    }
    return new SimpleFillSymbol({
      color: [109, 155, 181, 0.18],
      outline: { color: [145, 190, 210, 0.75], width: 0.9 },
    });
  }
  if (layerId === 'hydrography') {
    return new SimpleLineSymbol({ color: [86, 168, 206, 0.9], width: 1.5 });
  }
  if (layerId === 'fire') {
    return new SimpleMarkerSymbol({
      style: 'circle',
      color: [255, 84, 63, 0.9],
      size: selected ? 12 : 8,
      outline: { color: [255, 235, 220, 0.8], width: 0.7 },
    });
  }
  if (['assets', 'asset_exposure', 'asset_vulnerability', 'asset_criticality', 'interventions'].includes(layerId)) {
    const isPilot = properties.sourceDataset === 'osm_kano_pilot';
    const isExposed = ['exposed', 'candidate'].includes(String(properties.exposureStatus ?? '').toLowerCase());
    const fill = isExposed ? [240, 132, 66, 1] : isPilot ? [239, 173, 98, 1] : [82, 179, 174, 0.9];
    return new SimpleMarkerSymbol({
      style: 'circle',
      color: fill,
      size: selected ? 13 : isPilot ? 9 : 7,
      outline: { color: [248, 242, 232, 0.9], width: selected ? 1.8 : 0.8 },
    });
  }
  return new SimpleFillSymbol({
    color: [109, 155, 181, 0.18],
    outline: { color: [145, 190, 210, 0.75], width: 0.9 },
  });
}

export function AssetMap({
  overlays,
  selectedId,
  region,
  theme,
  basemapStyle,
  drawAreaRequest,
  clearAreaRequest,
  onSelect,
  onAreaResult,
  onMapError,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<MapView | null>(null);
  const selectionLayerRef = useRef<GraphicsLayer | null>(null);
  const overlayLayersRef = useRef<OverlayLayers>(new Map());
  const sketchRef = useRef<SketchViewModel | null>(null);
  const onSelectRef = useRef(onSelect);
  const onAreaResultRef = useRef(onAreaResult);
  const onMapErrorRef = useRef(onMapError);
  const overlaysRef = useRef(overlays);
  onSelectRef.current = onSelect;
  onAreaResultRef.current = onAreaResult;
  onMapErrorRef.current = onMapError;
  overlaysRef.current = overlays;

  useEffect(() => {
    if (!containerRef.current || viewRef.current) return;
    const map = new ArcGISMap({ basemap: mapBasemap(theme, basemapStyle) });
    const selectionLayer = new GraphicsLayer({ title: 'Area of interest', listMode: 'hide' });
    map.add(selectionLayer);
    selectionLayerRef.current = selectionLayer;
    const view = new MapView({
      container: containerRef.current,
      map,
      extent: mapExtent(region === 'kano' ? KANO_BBOX : KENYA_BBOX),
      constraints: { snapToZoom: false },
      ui: { components: ['zoom', 'compass'] },
      popup: { dockEnabled: true, dockOptions: { position: 'bottom-right', breakpoint: false } },
    });
    const sketch = new SketchViewModel({
      view,
      layer: selectionLayer,
      polygonSymbol: new SimpleFillSymbol({
        color: [240, 164, 106, 0.18],
        outline: { color: [255, 189, 125, 1], width: 2, style: 'dash' },
      }),
    });
    sketch.on('create', (event) => {
      if (event.state !== 'complete' || !event.graphic.geometry) return;
      const results = overlaysRef.current
        .filter((overlay) => overlay.visible && overlay.collection)
        .map((overlay) => {
          const features = overlay.collection?.features ?? [];
          const intersectingFeatures = features.filter((feature) => {
            const geometry = geometryFromGeoJson(feature.geometry);
            return geometry ? geometryEngine.intersects(event.graphic.geometry!, geometry) : false;
          }).length;
          return {
            layerId: overlay.id,
            title: overlay.title,
            intersectingFeatures,
            returnedFeatures: features.length,
          };
        });
      onAreaResultRef.current(results);
    });
    sketchRef.current = sketch;
    viewRef.current = view;
    view.when().then(() => {
      view.on('click', async (event) => {
        try {
          const hit = await view.hitTest(event, {
            include: [...overlayLayersRef.current.values()],
          });
          const result = hit.results.find((item) => item.type === 'graphic') as
            | { type: 'graphic'; graphic?: Graphic }
            | undefined;
          const assetId = result?.graphic?.attributes?.__assetId;
          if (typeof assetId === 'string' && assetId) onSelectRef.current(assetId);
        } catch (error) {
          onMapErrorRef.current(error instanceof Error ? error.message : String(error));
        }
      });
    }).catch((error: unknown) => {
      onMapErrorRef.current(error instanceof Error ? error.message : String(error));
    });

    return () => {
      sketch.destroy();
      view.destroy();
      viewRef.current = null;
      selectionLayerRef.current = null;
      sketchRef.current = null;
      overlayLayersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    const map = viewRef.current?.map;
    if (map) map.basemap = mapBasemap(theme, basemapStyle);
  }, [theme, basemapStyle]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const bbox = region === 'kano' ? KANO_BBOX : KENYA_BBOX;
    view.goTo(
      mapExtent(bbox),
      { duration: 650 },
    ).catch((error: unknown) => {
      if (error instanceof Error && error.name === 'AbortError') return;
      onMapErrorRef.current(error instanceof Error ? error.message : String(error));
    });
  }, [region]);

  useEffect(() => {
    const map = viewRef.current?.map;
    if (!map) return;
    const activeIds = new Set(overlays.map((overlay) => overlay.id));
    for (const [id, layer] of overlayLayersRef.current) {
      if (!activeIds.has(id)) {
        map.remove(layer);
        overlayLayersRef.current.delete(id);
      }
    }
    for (const overlay of overlays) {
      let layer = overlayLayersRef.current.get(overlay.id);
      if (!layer) {
        layer = new GraphicsLayer({ title: overlay.title, listMode: 'hide' });
        overlayLayersRef.current.set(overlay.id, layer);
        map.add(layer);
      }
      layer.title = overlay.title;
      layer.visible = overlay.visible;
      layer.removeAll();
      for (const feature of overlay.collection?.features ?? []) {
        const geometry = geometryFromGeoJson(feature.geometry);
        if (!geometry) continue;
        const properties = feature.properties ?? {};
        const id = String(feature.id ?? properties.energyAssetId ?? properties.administrativeUnitId ?? '');
        const title = String(properties.assetName ?? properties.name ?? properties.hazardType ?? overlay.title);
        const popup = makePopup(title, {
          ...properties,
          featureId: feature.id ?? id,
          ...(properties.energyAssetId
            ? { __assetId: properties.energyAssetId }
            : overlay.id === 'assets'
              ? { __assetId: id }
              : {}),
        });
        layer.add(
          new Graphic({
            geometry,
            symbol: symbolFor(overlay.id, properties, selectedId === id, feature.geometry!),
            attributes: popup.attributes,
            popupTemplate: popup.popupTemplate,
          }),
        );
      }
    }
  }, [overlays, selectedId]);

  useEffect(() => {
    if (drawAreaRequest === 0) return;
    sketchRef.current?.create('polygon');
  }, [drawAreaRequest]);

  useEffect(() => {
    if (clearAreaRequest === 0) return;
    selectionLayerRef.current?.removeAll();
    onAreaResultRef.current(null);
  }, [clearAreaRequest]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !selectedId) return;
    const selected = overlays
      .flatMap((overlay) => overlay.collection?.features ?? [])
      .find((feature) => String(feature.id) === selectedId);
    const coords = pointCoords(selected?.geometry);
    if (!coords) return;
    view.goTo(
      {
        center: new Point({ x: coords[0], y: coords[1], spatialReference: { wkid: 4326 } }),
        zoom: Math.max(view.zoom, region === 'kano' ? 11 : 7),
      },
      { duration: 700 },
    ).catch((error: unknown) => {
      if (error instanceof Error && error.name === 'AbortError') return;
      onMapErrorRef.current(error instanceof Error ? error.message : String(error));
    });
  }, [selectedId, overlays, region]);

  return <div ref={containerRef} className="absolute inset-0 esri-view" />;
}
