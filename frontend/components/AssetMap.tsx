import { useEffect, useRef } from 'react';
import Map from '@arcgis/core/Map';
import MapView from '@arcgis/core/views/MapView';
import GraphicsLayer from '@arcgis/core/layers/GraphicsLayer';
import Graphic from '@arcgis/core/Graphic';
import Point from '@arcgis/core/geometry/Point';
import Polyline from '@arcgis/core/geometry/Polyline';
import Polygon from '@arcgis/core/geometry/Polygon';
import Extent from '@arcgis/core/geometry/Extent';
import Basemap from '@arcgis/core/Basemap';
import TileLayer from '@arcgis/core/layers/TileLayer';
import SimpleMarkerSymbol from '@arcgis/core/symbols/SimpleMarkerSymbol';
import SimpleLineSymbol from '@arcgis/core/symbols/SimpleLineSymbol';
import SimpleFillSymbol from '@arcgis/core/symbols/SimpleFillSymbol';
import type { AssetFeature, GeoJsonCollection } from '../lib/api';
import { KANO_BBOX, PILOT_DATASET, pointCoords } from '../lib/api';
import '@arcgis/core/assets/esri/themes/dark/main.css';

export type MapLayers = {
  pilot: boolean;
  inventory: boolean;
  hydrography: boolean;
  floodReference: boolean;
};

type Props = {
  assets: AssetFeature[];
  hydrography: GeoJsonCollection | null;
  floodReference: GeoJsonCollection | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  layers: MapLayers;
};

const pilotSymbol = new SimpleMarkerSymbol({
  color: [217, 101, 43, 0.95],
  size: 10,
  outline: { color: [243, 235, 226, 1], width: 1.5 },
});

const pilotSelectedSymbol = new SimpleMarkerSymbol({
  color: [240, 164, 106, 1],
  size: 14,
  outline: { color: [255, 255, 255, 1], width: 2 },
});

const inventorySymbol = new SimpleMarkerSymbol({
  color: [150, 148, 142, 0.9],
  size: 7,
  outline: { color: [11, 12, 14, 1], width: 1 },
});

const hydroSymbol = new SimpleLineSymbol({
  color: [180, 176, 168, 0.85],
  width: 1.5,
});

const floodFill = new SimpleFillSymbol({
  color: [217, 101, 43, 0.2],
  outline: { color: [240, 164, 106, 0.8], width: 1 },
});

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

export function AssetMap({
  assets,
  hydrography,
  floodReference,
  selectedId,
  onSelect,
  layers,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<MapView | null>(null);
  const layersRef = useRef<{
    pilot: GraphicsLayer;
    inventory: GraphicsLayer;
    hydro: GraphicsLayer;
    flood: GraphicsLayer;
  } | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!containerRef.current || viewRef.current) return;

    const pilotLayer = new GraphicsLayer({ title: 'Pilot assets', listMode: 'hide' });
    const inventoryLayer = new GraphicsLayer({ title: 'Inventory', listMode: 'hide', visible: false });
    const hydroLayer = new GraphicsLayer({ title: 'Hydrography', listMode: 'hide', visible: false });
    const floodLayer = new GraphicsLayer({ title: 'Flood reference', listMode: 'hide', visible: false });

    const basemap = new Basemap({
      baseLayers: [
        new TileLayer({
          url: 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer',
        }),
        new TileLayer({
          url: 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer',
        }),
      ],
    });

    const map = new Map({
      basemap,
      layers: [floodLayer, hydroLayer, inventoryLayer, pilotLayer],
    });

    const view = new MapView({
      container: containerRef.current,
      map,
      extent: new Extent({
        xmin: KANO_BBOX.west,
        ymin: KANO_BBOX.south,
        xmax: KANO_BBOX.east,
        ymax: KANO_BBOX.north,
        spatialReference: { wkid: 4326 },
      }),
      constraints: { snapToZoom: false },
      ui: { components: ['zoom'] },
    });

    view.when(() => {
      view.on('click', async (event) => {
        const hit = await view.hitTest(event, {
          include: [pilotLayer, inventoryLayer],
        });
        const result = hit.results.find((r) => r.type === 'graphic') as
          | { type: 'graphic'; graphic?: Graphic }
          | undefined;
        const id = result?.graphic?.attributes?.id;
        if (typeof id === 'string' && id) onSelectRef.current(id);
      });
    });

    layersRef.current = {
      pilot: pilotLayer,
      inventory: inventoryLayer,
      hydro: hydroLayer,
      flood: floodLayer,
    };
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
      layersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const layersBag = layersRef.current;
    if (!layersBag) return;

    const pilot = assets.filter((a) => a.properties.sourceDataset === PILOT_DATASET);
    const inventory = assets.filter((a) => a.properties.sourceDataset !== PILOT_DATASET);

    layersBag.pilot.removeAll();
    layersBag.inventory.removeAll();

    for (const asset of pilot) {
      const geometry = geometryFromGeoJson(asset.geometry);
      if (!geometry) continue;
      layersBag.pilot.add(
        new Graphic({
          geometry,
          symbol: asset.id === selectedId ? pilotSelectedSymbol : pilotSymbol,
          attributes: { id: asset.id, name: asset.properties.name },
        }),
      );
    }

    for (const asset of inventory) {
      const geometry = geometryFromGeoJson(asset.geometry);
      if (!geometry) continue;
      layersBag.inventory.add(
        new Graphic({
          geometry,
          symbol: inventorySymbol,
          attributes: { id: asset.id, name: asset.properties.name },
        }),
      );
    }
  }, [assets, selectedId]);

  useEffect(() => {
    const layersBag = layersRef.current;
    if (!layersBag) return;
    layersBag.hydro.removeAll();
    for (const feature of hydrography?.features ?? []) {
      const geometry = geometryFromGeoJson(feature.geometry);
      if (!geometry) continue;
      layersBag.hydro.add(
        new Graphic({
          geometry,
          symbol: hydroSymbol,
          attributes: feature.properties || {},
        }),
      );
    }
  }, [hydrography]);

  useEffect(() => {
    const layersBag = layersRef.current;
    if (!layersBag) return;
    layersBag.flood.removeAll();
    for (const feature of floodReference?.features ?? []) {
      const geometry = geometryFromGeoJson(feature.geometry);
      if (!geometry) continue;
      layersBag.flood.add(
        new Graphic({
          geometry,
          symbol: floodFill,
          attributes: feature.properties || {},
        }),
      );
    }
  }, [floodReference]);

  useEffect(() => {
    const layersBag = layersRef.current;
    if (!layersBag) return;
    layersBag.pilot.visible = layers.pilot;
    layersBag.inventory.visible = layers.inventory;
    layersBag.hydro.visible = layers.hydrography;
    layersBag.flood.visible = layers.floodReference;
  }, [layers]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !selectedId) return;
    const feature = assets.find((a) => a.id === selectedId);
    const coords = pointCoords(feature?.geometry);
    if (!coords) return;
    view.goTo(
      {
        center: new Point({ x: coords[0], y: coords[1], spatialReference: { wkid: 4326 } }),
        zoom: Math.max(view.zoom, 11),
      },
      { duration: 700 },
    ).catch(() => undefined);
  }, [selectedId, assets]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
