/// <reference types="vite/client" />
/// <reference types="@esri/calcite-components/types/react" />

declare namespace GeoJSON {
  type Position = number[];

  interface Geometry {
    type: string;
    coordinates: Position | Position[] | Position[][] | Position[][][];
  }

  interface Feature {
    type: 'Feature';
    id?: string | number;
    geometry: Geometry | null;
    properties: Record<string, unknown> | null;
  }

  interface FeatureCollection {
    type: 'FeatureCollection';
    features: Feature[];
  }
}
