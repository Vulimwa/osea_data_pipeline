# OSEAS Frontend

This folder is the standalone React frontend. The backend API and national data pipeline live separately in [`../osea_data_pipe`](../osea_data_pipe). The app uses ArcGIS Maps SDK for JavaScript and Calcite Components. Light mode is the default; the header toggle switches to dark mode, and the selection is saved in the browser.

## Pages

| Route | Purpose |
| --- | --- |
| `/` | Map-first climate and energy risk view |
| `/map` | ArcGIS map with Kenya-wide and Kano pilot views |
| `/briefing` | Project briefing |
| `/evidence/:assetId` | Asset exposure and vulnerability evidence |

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173/**. By default, Vite proxies API requests to the deployed Render API at `https://osea-data-pipeline.onrender.com`. To use a local backend instead, set the proxy target before starting Vite:

```powershell
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:3000"
npm run dev
```

The browser reads the OSEAS API without user sign-in. This requires the backend's explicitly enabled public read-only mode; see the backend setup notes below. No Supabase credentials are needed in the frontend.

## Deploy to Vercel (manual)

Create a Vercel project for this repository and set its **Root Directory** to `frontend`. Vercel uses [`vercel.json`](./vercel.json) to run `npm run build`, publish `dist`, forward `/api/*` to `https://osea-data-pipeline.onrender.com`, and route frontend paths to the app shell.

In Vercel **Project → Settings → Environment Variables**, add:

| Variable | Value | Required |
| --- | --- | --- |
No Vercel environment variables are required for API access. `VITE_API_PROXY_TARGET` is only read by the local Vite dev server; Vercel's API rewrite is configured in `vercel.json`.

On the backend host (Render), set `OSEAS_PUBLIC_READ_API=true` to allow unauthenticated `GET` requests to the read-only OSEAS routes. Non-GET requests remain protected, and the flag is off by default. Keep `SUPABASE_SERVICE_ROLE_KEY` and the database URL only in backend secrets. This setup does not deploy the app.
