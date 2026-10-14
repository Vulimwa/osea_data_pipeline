import { useEffect, useRef } from 'react';
import maplibregl, { Map, Marker } from 'maplibre-gl';
import {
  AssetFeature,
  KANO_BBOX,
  PILOT_DATASET,
  pointCoords,
} from '../lib/api';

type Props = {
  assets: AssetFeature[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  pilotOnly: boolean;
};

function markerColor(feature: AssetFeature, selected: boolean): string {
  if (selected) return '#f3ebe2';
  if (feature.properties.sourceDataset === PILOT_DATASET) return '#c45c26';
  return '#3d8f8f';
}

export function AssetMap({ assets, selectedId, onSelect, pilotOnly }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const markersRef = useRef<Marker[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      bounds: [
        [KANO_BBOX.west, KANO_BBOX.south],
        [KANO_BBOX.east, KANO_BBOX.north],
      ],
      fitBoundsOptions: { padding: 48 },
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    mapRef.current = map;
    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    const visible = pilotOnly
      ? assets.filter((a) => a.properties.sourceDataset === PILOT_DATASET)
      : assets;

    for (const feature of visible) {
      const coords = pointCoords(feature.geometry);
      if (!coords) continue;
      const el = document.createElement('button');
      el.type = 'button';
      el.setAttribute('aria-label', feature.properties.name || feature.id);
      const selected = feature.id === selectedId;
      const size = selected ? 16 : 11;
      el.style.cssText = [
        `width:${size}px`,
        `height:${size}px`,
        'border-radius:50%',
        `background:${markerColor(feature, selected)}`,
        `border:2px solid ${selected ? '#0c1a1f' : 'rgba(12,26,31,0.55)'}`,
        'padding:0',
        'cursor:pointer',
        selected ? 'box-shadow:0 0 0 4px rgba(196,92,38,0.45)' : '',
        'transition: transform 180ms ease, box-shadow 180ms ease',
      ].join(';');
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        onSelect(feature.id);
      });
      const marker = new maplibregl.Marker({ element: el }).setLngLat(coords).addTo(map);
      markersRef.current.push(marker);
    }
  }, [assets, selectedId, onSelect, pilotOnly]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedId) return;
    const feature = assets.find((a) => a.id === selectedId);
    if (!feature) return;
    const coords = pointCoords(feature.geometry);
    if (!coords) return;
    map.easeTo({ center: coords, zoom: Math.max(map.getZoom(), 11), duration: 700 });
  }, [selectedId, assets]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
