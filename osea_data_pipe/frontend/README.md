# OSEAS frontend — Kano plains pilot

## Stack

- React 19 + React DOM
- `react-router-dom` — Overview / Map / Evidence pages
- `@tanstack/react-query` — API queries
- `@arcgis/core` — ArcGIS Maps SDK (MapView + GraphicsLayer)
- `@esri/calcite-components` + `@esri/calcite-ui-icons` — shell UI
- `lucide-react` (available), `clsx` + `tailwind-merge`
- Vite + `@vitejs/plugin-react` + TypeScript
- Tailwind CSS v4 (`@tailwindcss/vite`)

## Pages

| Route | Job |
| --- | --- |
| `/` | Brand overview + CTAs |
| `/map` | Full-bleed ArcGIS map |
| `/evidence/:assetId` | Asset flood / vulnerability evidence |

## Run

```powershell
npm run start
npm run dev:ui
```

Open **http://localhost:5173/**
