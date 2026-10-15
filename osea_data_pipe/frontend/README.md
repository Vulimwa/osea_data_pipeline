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
npm start
npm run dev:ui
```

Open **http://localhost:5173/**. The Vite dev server proxies `/api` to the local API at `http://127.0.0.1:3000`.

To exercise the deployed API from the local UI, set the Vite proxy target before starting the dev server:

```powershell
$env:VITE_API_PROXY_TARGET = "https://osea-data-pipeline.onrender.com"
npm run dev:ui
```

## Deploy to Vercel

Create a Vercel project for this repository with the root directory set to `osea_data_pipe`. The checked-in `vercel.json` builds the standalone `frontend/` application and serves the React routes. It proxies `/api/*` requests to the existing Render API, so the database/API deployment remains separate and unchanged.

Use the project settings from `vercel.json` (`npm run build:ui`, output directory `dist-frontend`). After deployment, open the Vercel project URL; the Kano demo is at `/map`. No database credentials or API secrets are required in Vercel.
