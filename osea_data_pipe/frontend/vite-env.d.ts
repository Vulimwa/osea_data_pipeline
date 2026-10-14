/// <reference types="vite/client" />

declare namespace GeoJSON {
  type Position = number[];
  interface Geometry {
    type: string;
    coordinates: Position | Position[] | Position[][] | Position[][][];
  }
}
