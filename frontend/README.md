# OSEAS map application

This is the React frontend for OSEAS. It uses the ArcGIS Maps SDK for JavaScript and Calcite Components to display OSEAS API layers, asset and administrative evidence, and map controls. The map defaults to OpenStreetMap; it does not connect directly to Earth Engine or PostgreSQL.

## Pages

| Route | Purpose |
| --- | --- |
| `/` and `/map` | Interactive Kenya and Kano pilot map |
| `/briefing` | Project briefing |
| `/evidence/:assetId` | Asset evidence |
| `/evidence/area/:level/:unitId` | County or ward evidence |

## Local development

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The Vite configuration proxies API requests to the configured target. The default target is `https://osea-data-pipeline.onrender.com`; point it at a local API when needed:

```powershell
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:3000"
npm run dev
```

The browser uses the OSEAS read API. No database password, Earth Engine credential, or Supabase service-role key belongs in frontend configuration. Production API access is controlled by the backend's bearer-token policy or its explicit public-read setting.

## Build

```powershell
npm run build
```

This runs the TypeScript check and creates the production bundle in `dist/`.

## Deployment

For Vercel, set the project root to `frontend`; the repository's `frontend/vercel.json` describes the build and API rewrites. Configure the backend's allowed CORS origin and authentication separately. See the backend [`docs/SETUP.md`](../osea_data_pipe/docs/SETUP.md) and [`docs/FRONTEND_INTEGRATION_GUIDE.md`](../osea_data_pipe/docs/FRONTEND_INTEGRATION_GUIDE.md).
