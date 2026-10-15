# OSEAS Frontend — Kano Plains Pilot

This folder is the standalone React frontend. The backend API and national data pipeline live separately in [`../osea_data_pipe`](../osea_data_pipe).

## Pages

| Route | Purpose |
| --- | --- |
| `/` | Pilot briefing |
| `/map` | ArcGIS map of the Kano pilot |
| `/evidence/:assetId` | Asset exposure and vulnerability evidence |

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173/**. By default, the Vite dev server proxies API requests to the local backend at `http://127.0.0.1:3000`; start that separately from [`osea_data_pipe`](../osea_data_pipe), for example with `npm run dev` in that folder.

To use the deployed Render API while previewing locally:

```powershell
cd frontend
$env:VITE_API_PROXY_TARGET = "https://osea-data-pipeline.onrender.com"
npm run dev
```

## Deploy to Vercel

Create a Vercel project for this repository and set its **Root Directory** to `frontend`. This keeps the UI deployment separate from the backend and national pipeline in `osea_data_pipe`.

Vercel uses the settings in [`vercel.json`](./vercel.json): install the frontend dependencies, run `npm run build`, and publish `dist`. The rewrite forwards `/api/*` to the existing Render API. No database credentials or API secrets are needed in Vercel. After you deploy, open the project URL; the map is at `/map`.
